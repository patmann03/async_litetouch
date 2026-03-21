import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple, Any

_LOGGER = logging.getLogger(__name__)


# ----------------------------
# Parsing helpers
# ----------------------------


def _int_auto(s: str) -> int:
    s = s.strip()
    # allow negatives like -1
    if s.startswith("-"):
        return int(s)
    try:
        return int(s)  # decimal
    except ValueError:
        return int(s, 16)  # hex (e.g. "E


@dataclass(frozen=True)
class LiteTouchMessage:
    """Raw parsed message from the controller."""

    raw: str
    parts: Tuple[str, ...]  # comma-split fields


@dataclass(frozen=True)
class LiteTouchResponse:
    """
    Structured response:
      - kind examples: RCACK, RQRES, RDACK, RTRES, RLEDU, RMODU, REVNT
      - cmd is present for RQRES/RCACK/RDACK style responses where the command is echoed.
    """

    raw: str
    kind: str
    cmd: Optional[str]
    fields: Tuple[str, ...]


def _parse_line(line: str) -> LiteTouchMessage:
    line = line.strip("\r\n")
    parts = tuple(p.strip() for p in line.split(",") if p is not None)
    return LiteTouchMessage(raw=line, parts=parts)


def _to_response(msg: LiteTouchMessage) -> LiteTouchResponse:
    # Typical formats from the doc include:
    #   R,RCACK,<CMD>[,...]
    #   R,RDACK,<CMD>
    #   R,RQRES,<CMD>,<payload...>
    #   R,RTRES,<result>,<set>,<port>,<xxxx...>
    #   R,RLEDU,<station>,<bitmap>
    #   R,RMODU,<modulehex>,<map>,level1..level8
    #   R,REVNT,<SWP|SWH|SWR|TMB|TME|USR>,<value>
    parts = msg.parts
    if len(parts) < 2:
        return LiteTouchResponse(raw=msg.raw, kind="UNKNOWN", cmd=None, fields=parts)

    if parts[0] != "R":
        # Some integrations still prefix with R; if not, keep raw
        return LiteTouchResponse(
            raw=msg.raw, kind="NONSTANDARD", cmd=None, fields=parts
        )

    kind = parts[1]

    cmd = None
    fields = parts[2:]

    # For ACK/Query responses, the third field is usually the echoed command name
    if kind in ("RCACK", "RDACK", "RQRES") and len(parts) >= 3:
        cmd = parts[2]
        fields = parts[3:]

    return LiteTouchResponse(raw=msg.raw, kind=kind, cmd=cmd, fields=fields)


# ----------------------------
# Transport: one TCP connection
# ----------------------------


class _LiteTouchTransport:
    """
    One persistent TCP connection.
    - reader loop reads until '\\r'
    - request() sends command and awaits matching response
    """

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        *,
        reconnect: bool = True,
        reconnect_min_delay: float = 0.5,
        reconnect_max_delay: float = 10.0,
        on_message: Optional[Callable[[LiteTouchResponse], None]] = None,
        print_raw: bool = False,
        send_lock: Optional[asyncio.Lock] = None,
        keepalive_interval: float = 60.0,
        send_delay_ms: float = 10.0,
    ):
        self.name = name
        self.host = host
        self.port = port
        self.reconnect = reconnect
        self.reconnect_min_delay = reconnect_min_delay
        self.reconnect_max_delay = reconnect_max_delay
        self.on_message = on_message
        self.print_raw = print_raw

        self.keepalive_interval = keepalive_interval
        self._keepalive_task: Optional[asyncio.Task] = None

        self.send_delay_ms = send_delay_ms
        self._last_send_time: float = 0.0

        self._send_lock = send_lock or asyncio.Lock()
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

        # Futures waiting for a response: (matcher, future)
        self._waiters: List[
            Tuple[Callable[[LiteTouchResponse], bool], asyncio.Future]
        ] = []

        self._reader_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def start(self) -> None:

        self._stop.clear()
        self._reader_task = asyncio.create_task(self._run(), name=f"{self.name}-reader")
        if self.keepalive_interval and self.keepalive_interval > 0:
            self._keepalive_task = asyncio.create_task(
                self._keepalive_loop(), name=f"{self.name}-keepalive"
            )

    async def close(self) -> None:
        self._stop.set()
        if self._keepalive_task:
            self._keepalive_task.cancel()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await self._keepalive_task

        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await self._reader_task
        await self._disconnect()

        # Cancel any pending waiters
        for _, fut in self._waiters:
            if not fut.done():
                fut.cancel()
        self._waiters.clear()

    async def _disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, asyncio.CancelledError):
                pass
        self._reader = None
        self._writer = None

    async def _connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        _LOGGER.info("[%s] connected to %s:%s", self.name, self.host, self.port)
        await self.send("R,SIEVN,5") # enable module and keypad events
        

    async def _keepalive_loop(self) -> None:
        """
        Periodically send DGCLK (get clock) and await the DGCLK response to
        confirm the controller is alive.  On failure, disconnect so _run()
        can reconnect with backoff.
        """
        # small offset so we don't hammer immediately at startup
        await asyncio.sleep(2.0)

        while not self._stop.is_set():
            try:
                # Only send keepalive if connected; if not, let _run() reconnect.
                if self.is_connected:
                    await self.request(
                        "R,DGCLK",
                        expect=lambda r: r.kind == "RQRES" and r.cmd == "DGCLK",
                        timeout=5.0,
                    )
                    _LOGGER.debug("[%s] keepalive OK (DGCLK)", self.name)
            except asyncio.CancelledError:
                return  # stop immediately; don't run the interval sleep
            except Exception as e:
                _LOGGER.warning(
                    "[%s] keepalive failed: %s — forcing disconnect", self.name, e
                )
                await self._disconnect()

            try:
                await asyncio.sleep(self.keepalive_interval)
            except asyncio.CancelledError:
                return  # cancelled during sleep; stop cleanly

    async def _run(self) -> None:
        delay = self.reconnect_min_delay
        while not self._stop.is_set():
            try:
                if not self.is_connected:
                    await self._connect()
                    delay = self.reconnect_min_delay

                assert self._reader is not None
                # Messages are terminated by carriage return per spec
                raw = await self._reader.readuntil(separator=b"\r")
                line = raw.decode("ascii", errors="replace").strip("\r\n")
                msg = _parse_line(line)
                resp = _to_response(msg)

                if self.print_raw:
                    print(f"[{self.name}] << {resp.raw}")

                # First satisfy any waiter that matches
                delivered = False
                for matcher, fut in list(self._waiters):
                    if fut.done():
                        self._waiters.remove((matcher, fut))
                        continue
                    if matcher(resp):
                        fut.set_result(resp)
                        self._waiters.remove((matcher, fut))
                        delivered = True
                        break

                # If not a direct response, dispatch as async event/notification
                if (not delivered) and self.on_message:
                    try:
                        self.on_message(resp)
                    except Exception:
                        _LOGGER.exception("[%s] on_message handler error", self.name)

            except asyncio.IncompleteReadError:
                _LOGGER.warning("[%s] connection closed by peer", self.name)
                await self._disconnect()
            except (ConnectionError, OSError) as e:
                _LOGGER.warning("[%s] connection error: %s", self.name, e)
                await self._disconnect()
            except asyncio.LimitOverrunError:
                # If controller sends malformed line without delimiter; try continue
                _LOGGER.warning(
                    "[%s] read limit overrun; resetting connection", self.name
                )
                await self._disconnect()
            except asyncio.CancelledError:
                break
            except Exception:
                _LOGGER.exception(
                    "[%s] unexpected error; resetting connection", self.name
                )
                await self._disconnect()

            if self.reconnect and not self._stop.is_set() and not self.is_connected:
                await asyncio.sleep(delay)
                delay = min(self.reconnect_max_delay, delay * 2)

    async def send(self, command: str) -> None:
        """Send a command without waiting for a response."""
        if not command.endswith("\r"):
            command = command + "\r"

        async with self._send_lock:
            if self.send_delay_ms > 0 and self._last_send_time > 0:
                elapsed_ms = (time.monotonic() - self._last_send_time) * 1000
                remaining_ms = self.send_delay_ms - elapsed_ms
                if remaining_ms > 0:
                    await asyncio.sleep(remaining_ms / 1000)

            await self._ensure_connected()
            assert self._writer is not None
            if self.print_raw:
                print(f"[{self.name}] >> {command.strip()}")
            self._writer.write(command.encode("ascii", errors="replace"))
            await self._writer.drain()
            self._last_send_time = time.monotonic()

    async def request(
        self,
        command: str,
        *,
        expect: Callable[[LiteTouchResponse], bool],
        timeout: float = 2.5,
    ) -> LiteTouchResponse:
        """
        Send command then await a matching response.
        Many commands in the doc have ACK or RQRES formats.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._waiters.append((expect, fut))

        await self.send(command)

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except Exception:
            # Ensure we remove the waiter if still present
            for matcher, wfut in list(self._waiters):
                if wfut is fut:
                    self._waiters.remove((matcher, wfut))
                    break
            raise

    async def _ensure_connected(self) -> None:
        if self.is_connected:
            return
        # Wait briefly for reader loop to reconnect
        for _ in range(25):
            if self.is_connected:
                return
            await asyncio.sleep(0.1)
        raise ConnectionError(f"[{self.name}] not connected to {self.host}:{self.port}")


# ----------------------------
# Public client: pool + API
# ----------------------------


class LiteTouchClient:
    """
    Async LiteTouch RTC Protocol client.

    Design notes:
    - Commands are ASCII comma-delimited, terminated with '\\r'.
    - Controller can send unsolicited notifications (RLEDU, RMODU, REVNT).
    - To avoid interleaving command responses with notifications, you can use a
      separate 'event' connection and/or a pool of command connections.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        command_connections: int = 2,
        use_separate_event_connection: bool = True,
        print_raw: bool = False,
    ):
        self.host = host
        self.port = port
        self.command_connections = max(1, int(command_connections))
        self.use_separate_event_connection = use_separate_event_connection
        self.print_raw = print_raw

        self._rr = 0  # round-robin index

        # Shared lock per connection (keeps each connection sequential)
        self._cmd_transports: List[_LiteTouchTransport] = []
        for i in range(self.command_connections):
            self._cmd_transports.append(
                _LiteTouchTransport(
                    name=f"cmd{i + 1}",
                    host=self.host,
                    port=self.port,
                    on_message=self._handle_unsolicited,
                    print_raw=self.print_raw,
                    keepalive_interval=0,  # keepalive runs on event transport only
                )
            )

        self._event_transport: Optional[_LiteTouchTransport] = None
        if self.use_separate_event_connection:
            self._event_transport = _LiteTouchTransport(
                name="event",
                host=self.host,
                port=self.port,
                on_message=self._handle_unsolicited,
                print_raw=self.print_raw,
                keepalive_interval=30.0,
            )

        # User event callbacks
        self.on_led_update: Optional[Callable[[int, str], None]] = None
        self.on_module_update: Optional[Callable[[int, str, List[int]], None]] = None
        self.on_event: Optional[Callable[[str, str], None]] = None
        self.on_any_message: Optional[Callable[[LiteTouchResponse], None]] = None

    async def start(self) -> None:
        for t in self._cmd_transports:
            await t.start()
        if self._event_transport:
            await self._event_transport.start()

    async def close(self) -> None:
        for t in self._cmd_transports:
            await t.close()
        if self._event_transport:
            await self._event_transport.close()

    def _pick_cmd_transport(self) -> _LiteTouchTransport:
        t = self._cmd_transports[self._rr % len(self._cmd_transports)]
        self._rr += 1
        return t

    def _events_transport(self) -> _LiteTouchTransport:
        return self._event_transport or self._cmd_transports[0]

    def _handle_unsolicited(self, resp: LiteTouchResponse) -> None:
        # Notifications documented: RLEDU, RMODU, REVNT
        if resp.kind == "RLEDU":
            # fields: station, bitmap
            if len(resp.fields) >= 2:
                # station = int(resp.fields[0], 10)
                station = str(resp.fields[0])
                bitmap = resp.fields[1]
                if self.on_led_update:
                    self.on_led_update(station, bitmap)
        elif resp.kind == "RMODU":
            # fields: module_hex, map, level1..level8
            if len(resp.fields) >= 3:
                module_hex = resp.fields[0]
                changed_map = resp.fields[1]
                levels = []
                for x in resp.fields[2:]:
                    try:
                        levels.append(int(x))
                    except ValueError:
                        levels.append(-999)
                module_addr = int(module_hex, 16)
                if self.on_module_update:
                    self.on_module_update(module_addr, changed_map, levels)
        elif resp.kind == "REVNT":
            # fields: type, value
            if len(resp.fields) >= 2 and self.on_event:
                self.on_event(resp.fields[0], resp.fields[1])

        if self.on_any_message:
            self.on_any_message(resp)

    # ----------------------------
    # Low-level helpers
    # ----------------------------

    @staticmethod
    def _cmd(*parts: Any) -> str:
        # Build "R,<cmd>,<arg1>,<arg2>...\r"
        s = ",".join(str(p) for p in parts)
        return s + "\r"

    @staticmethod
    def _expect_ack(kind: str, cmd: str) -> Callable[[LiteTouchResponse], bool]:
        # Match: R,<kind>,<cmd>
        def _m(resp: LiteTouchResponse) -> bool:
            return resp.kind == kind and resp.cmd == cmd

        return _m

    @staticmethod
    def _expect_query(cmd: str) -> Callable[[LiteTouchResponse], bool]:
        # Match: R,RQRES,<cmd>,...
        def _m(resp: LiteTouchResponse) -> bool:
            return resp.kind == "RQRES" and resp.cmd == cmd

        return _m

    @staticmethod
    def _expect_rtres() -> Callable[[LiteTouchResponse], bool]:
        def _m(resp: LiteTouchResponse) -> bool:
            return resp.kind == "RTRES"

        return _m

    # ----------------------------
    # Notify Setup Commands
    # ----------------------------

    async def set_internal_event_notify(self, level: int) -> None:
        # R,SIEVN,[0..7]  (mutually exclusive levels)
        await self._events_transport().send(self._cmd("R", "SIEVN", level))

    async def set_station_notify(self, station: int, mode: int) -> None:
        # R,SSTNN,<xxx>,[n] where n=0..3
        st = f"{station:03d}"
        await self._events_transport().send(self._cmd("R", "SSTNN", st, mode))

    async def set_module_notify(self, module_hex: str, mode: int) -> None:
        # R,SMODN,<xxx>,[n] where xxx module address in hex, n=0..1
        await self._events_transport().send(self._cmd("R", "SMODN", module_hex, mode))

    # ----------------------------
    # Diagnostic Commands
    # ----------------------------

    async def full_station_test(self, timeout: float = 5.0) -> LiteTouchResponse:
        # R,DFSTS -> multiple R,RTRES,... responses
        t = self._pick_cmd_transport()
        return await t.request(
            self._cmd("R", "DFSTS"), expect=self._expect_rtres(), timeout=timeout
        )

    async def station_test(self, timeout: float = 5.0) -> LiteTouchResponse:
        # R,DSTST -> R,RTRES,...
        t = self._pick_cmd_transport()
        return await t.request(
            self._cmd("R", "DSTST"), expect=self._expect_rtres(), timeout=timeout
        )

    async def full_module_test(self, timeout: float = 5.0) -> LiteTouchResponse:
        # R,DFMTS -> R,RTRES,...
        t = self._pick_cmd_transport()
        return await t.request(
            self._cmd("R", "DFMTS"), expect=self._expect_rtres(), timeout=timeout
        )

    async def module_test(self, timeout: float = 5.0) -> LiteTouchResponse:
        # R,DMTST -> R,RTRES,...
        t = self._pick_cmd_transport()
        return await t.request(
            self._cmd("R", "DMTST"), expect=self._expect_rtres(), timeout=timeout
        )

    async def get_clock(self) -> str:
        # R,DGCLK -> R,RQRES,DGCLK,yyyymmddhhmmss
        t = self._pick_cmd_transport()
        resp = await t.request(
            self._cmd("R", "DGCLK"), expect=self._expect_query("DGCLK"), timeout=3.0
        )
        return resp.fields[0] if resp.fields else ""

    async def set_clock(self, yyyymmddhhmmss: str) -> None:
        # R,DSCLK,yyyymmddhhmmss -> none
        await self._pick_cmd_transport().send(self._cmd("R", "DSCLK", yyyymmddhhmmss))

    async def get_sunrise(self) -> LiteTouchResponse:
        # R,CGTSR -> doc shows RCACK text response
        t = self._pick_cmd_transport()
        return await t.request(
            self._cmd("R", "CGTSR"),
            expect=self._expect_ack("RCACK", "CGTSR"),
            timeout=3.0,
        )

    async def get_sunset(self) -> LiteTouchResponse:
        # R,CGTSS -> R,RQRES,CGTSS,...
        t = self._pick_cmd_transport()
        return await t.request(
            self._cmd("R", "CGTSS"), expect=self._expect_query("CGTSS"), timeout=3.0
        )

    async def get_module_levels(self, module_hex: str) -> Tuple[str, List[int]]:
        # R,DGMLV,<mmm> -> R,RQRES,DGMLV,<map>,<level1>..
        t = self._pick_cmd_transport()
        resp = await t.request(
            self._cmd("R", "DGMLV", module_hex),
            expect=self._expect_query("DGMLV"),
            timeout=3.0,
        )
        _LOGGER.debug(f"Response: {resp}")
        if not resp.fields:
            return "", []
        # bitmap = resp.fields[2:]
        bitmap = resp.fields[1]
        # levels = [int(x) for x in resp.fields[1:] if x != ""]
        levels = [_int_auto(x) for x in resp.fields[2:] if x != ""]
        return bitmap, levels

    async def set_module_levels(
        self,
        module_hex: str,
        bitmap_hex: str,
        time_seconds: int,
        levels: List[int],
    ) -> None:
        # R,DSMLV,<mmm>,<map>,<time>,<level1>..<leveln> -> R,RDACK,DSMLV
        t = self._pick_cmd_transport()
        cmd = self._cmd("R", "DSMLV", module_hex, bitmap_hex, time_seconds, *levels)
        await t.request(cmd, expect=self._expect_ack("RDACK", "DSMLV"), timeout=3.0)

    async def memory_monitor_test(self, device: int, on_off: int) -> None:
        # R,DMMTS,[1|2|3],[0|1] -> none
        await self._pick_cmd_transport().send(self._cmd("R", "DMMTS", device, on_off))

    # ----------------------------
    # Function Commands
    # ----------------------------

    async def get_load_state(self, mmmo: str) -> int:
        # R,CGLST,<mmmo> -> R,RQRES,CGLST,<b>
        t = self._pick_cmd_transport()
        resp = await t.request(
            self._cmd("R", "CGLST", mmmo),
            expect=self._expect_query("CGLST"),
            timeout=3.0,
        )
        return int(resp.fields[0]) if resp.fields else 0

    async def get_load_level(self, mmmo: str) -> int:
        # R,CGLLV,<mmmo> -> R,RQRES,CGLLV,<level>
        t = self._pick_cmd_transport()
        resp = await t.request(
            self._cmd("R", "CGLLV", mmmo),
            expect=self._expect_query("CGLLV"),
            timeout=3.0,
        )
        return int(resp.fields[0]) if resp.fields else 0

    async def set_loads_on(self, load_group: int) -> None:
        # R,CSLON,<group> -> R,RCACK,CSLON
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSLON", load_group),
            expect=self._expect_ack("RCACK", "CSLON"),
            timeout=3.0,
        )

    async def set_loads_off(self, load_group: int) -> None:
        # R,CSLOF,<group> -> R,RCACK,CSLOF
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSLOF", load_group),
            expect=self._expect_ack("RCACK", "CSLOF"),
            timeout=3.0,
        )

    async def set_load_levels(self, load_group: int) -> None:
        # R,CSLLV,<group> -> R,RCACK,CSLLV
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSLLV", load_group),
            expect=self._expect_ack("RCACK", "CSLLV"),
            timeout=3.0,
        )

    async def set_previous_load_states(self, load_group: int) -> None:
        # R,CSPLS,<group> -> R,RCACK,CSPLS
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSPLS", load_group),
            expect=self._expect_ack("RCACK", "CSPLS"),
            timeout=3.0,
        )

    async def copy_current_to_preset_levels(self, load_group: int) -> None:
        # R,CGCLV,<group> -> R,RCACK,CGCLV
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CGCLV", load_group),
            expect=self._expect_ack("RCACK", "CGCLV"),
            timeout=3.0,
        )

    async def copy_current_to_min_levels(self, load_group: int) -> None:
        # R,CGMIN,<group> -> R,RCACK,CGMIN
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CGMIN", load_group),
            expect=self._expect_ack("RCACK", "CGMIN"),
            timeout=3.0,
        )

    async def copy_current_to_max_levels(self, load_group: int) -> None:
        # R,CGMAX,<group> -> R,RCACK,CGMAX
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CGMAX", load_group),
            expect=self._expect_ack("RCACK", "CGMAX"),
            timeout=3.0,
        )

    async def get_load_value(self, mmmo: str, load_group: int) -> int:
        # R,CGLVA,<mmmo>,<group> -> R,RQRES,CGLVA,<level>
        t = self._pick_cmd_transport()
        resp = await t.request(
            self._cmd("R", "CGLVA", mmmo, load_group),
            expect=self._expect_query("CGLVA"),
            timeout=3.0,
        )
        return int(resp.fields[0]) if resp.fields else 0

    async def set_preset_value(self, mmmo: str, load_group: int, value: int) -> None:
        # R,CSLVA,<mmmo>,<group>,<value> -> R,RCACK,CSLVA
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSLVA", mmmo, load_group, value),
            expect=self._expect_ack("RCACK", "CSLVA"),
            timeout=3.0,
        )

    async def get_led_state(self, ssso: str) -> int:
        # R,CGLED,<ssso> -> R,RQRES,CGLED,<bool>
        t = self._pick_cmd_transport()
        resp = await t.request(
            self._cmd("R", "CGLED", ssso),
            expect=self._expect_query("CGLED"),
            timeout=3.0,
        )
        return int(resp.fields[0]) if resp.fields else 0

    async def get_led_states(self, sss: str) -> int:
        # R,CGLES,<sss> -> R,RQRES,CGLES,<xx>
        t = self._pick_cmd_transport()
        resp = await t.request(
            self._cmd("R", "CGLES", sss),
            expect=self._expect_query("CGLES"),
            timeout=3.0,
        )
        return int(resp.fields[0]) if resp.fields else 0

    async def get_valid_switches(self, sss: str) -> Tuple[str, int]:
        # R,CGVSW,<sss> -> R,RQRES,CGVSW,<ssss>,<xx>
        t = self._pick_cmd_transport()
        resp = await t.request(
            self._cmd("R", "CGVSW", sss),
            expect=self._expect_query("CGVSW"),
            timeout=3.0,
        )
        station_hex = resp.fields[0] if len(resp.fields) > 0 else ""
        bitmap_dec = int(resp.fields[1]) if len(resp.fields) > 1 else 0
        return station_hex, bitmap_dec

    async def set_led_on(self, ssso: str) -> None:
        # R,CLDON,<ssso> -> R,RCACK,CLDON
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CLDON", ssso),
            expect=self._expect_ack("RCACK", "CLDON"),
            timeout=3.0,
        )

    async def set_led_off(self, ssso: str) -> None:
        # R,CLDOF,<ssso> -> R,RCACK,CLDOF
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CLDOF", ssso),
            expect=self._expect_ack("RCACK", "CLDOF"),
            timeout=3.0,
        )

    async def open_loads(self, load_group: int) -> None:
        # R,COPNL,<group> -> R,RCACK,COPNL
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "COPNL", load_group),
            expect=self._expect_ack("RCACK", "COPNL"),
            timeout=3.0,
        )

    async def close_loads(self, load_group: int) -> None:
        # R,CCLSL,<group> -> R,RCACK,CCLSL
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CCLSL", load_group),
            expect=self._expect_ack("RCACK", "CCLSL"),
            timeout=3.0,
        )

    async def stop_loads(self, load_group: int) -> None:
        # R,CSTPL,<group> -> R,RCACK,CSTPL
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSTPL", load_group),
            expect=self._expect_ack("RCACK", "CSTPL"),
            timeout=3.0,
        )

    async def press_switch(self, ssso: str) -> None:
        # R,CPRSW,<ssso> -> R,RCACK,CPRSW
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CPRSW", ssso),
            expect=self._expect_ack("RCACK", "CPRSW"),
            timeout=3.0,
        )

    async def hold_switch(self, ssso: str) -> None:
        # R,CHDSW,<ssso> -> R,RCACK,CHDSW
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CHDSW", ssso),
            expect=self._expect_ack("RCACK", "CHDSW"),
            timeout=3.0,
        )

    async def release_switch(self, ssso: str) -> None:
        # R,CRLSW,<ssso> -> R,RCACK,CRLSW
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CRLSW", ssso),
            expect=self._expect_ack("RCACK", "CRLSW"),
            timeout=3.0,
        )

    async def toggle_switch(self, ssso: str) -> None:
        # R,CTGSW,<ssso> -> R,RCACK,CTGSW
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CTGSW", ssso),
            expect=self._expect_ack("RCACK", "CTGSW"),
            timeout=3.0,
        )

    async def press_hold_switch(self, ssso: str) -> None:
        # R,CPHSW,<ssso> -> R,RCACK,CPHSW
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CPHSW", ssso),
            expect=self._expect_ack("RCACK", "CPHSW"),
            timeout=3.0,
        )

    async def toggle_loads_on(self, load_group: int) -> None:
        # R,CTLON,<group> -> R,RCACK,CTLON
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CTLON", load_group),
            expect=self._expect_ack("RCACK", "CTLON"),
            timeout=3.0,
        )

    async def toggle_loads_off(self, load_group: int) -> None:
        # R,CTLOF,<group> -> R,RCACK,CTLOF
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CTLOF", load_group),
            expect=self._expect_ack("RCACK", "CTLOF"),
            timeout=3.0,
        )

    async def start_ramp(self, load_group: int) -> None:
        # R,CSTRP,<group> -> R,RCACK,CSTRP
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSTRP", load_group),
            expect=self._expect_ack("RCACK", "CSTRP"),
            timeout=3.0,
        )

    async def stop_ramp(self, load_group: int) -> None:
        # R,CSPRP,<group> -> R,RCACK,CSPRP
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSPRP", load_group),
            expect=self._expect_ack("RCACK", "CSPRP"),
            timeout=3.0,
        )

    async def start_ramp_to_min(self, load_group: int) -> None:
        # R,CSRMN,<group> -> R,RCACK,CSRMN
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSRMN", load_group),
            expect=self._expect_ack("RCACK", "CSRMN"),
            timeout=3.0,
        )

    async def start_ramp_to_max(self, load_group: int) -> None:
        # R,CSRMX,<group> -> R,RCACK,CSRMX
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSRMX", load_group),
            expect=self._expect_ack("RCACK", "CSRMX"),
            timeout=3.0,
        )

    async def lock_loads(self, load_group: int) -> None:
        # R,CLCKL,<group> -> R,RCACK,CLCKL
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CLCKL", load_group),
            expect=self._expect_ack("RCACK", "CLCKL"),
            timeout=3.0,
        )

    async def unlock_loads(self, load_group: int) -> None:
        # R,CUNLL,<group> -> R,RCACK,CUNLL
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CUNLL", load_group),
            expect=self._expect_ack("RCACK", "CUNLL"),
            timeout=3.0,
        )

    async def lock_switch(self, ssso: str) -> None:
        # R,CLCKS,<ssso> -> R,RCACK,CLCKS
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CLCKS", ssso),
            expect=self._expect_ack("RCACK", "CLCKS"),
            timeout=3.0,
        )

    async def unlock_switch(self, ssso: str) -> None:
        # R,CUNLS,<ssso> -> R,RCACK,CUNLS
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CUNLS", ssso),
            expect=self._expect_ack("RCACK", "CUNLS"),
            timeout=3.0,
        )

    async def lock_timer(self, timer_id: int) -> None:
        # R,CLCKT,<val> -> R,RCACK,CLCKT
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CLCKT", timer_id),
            expect=self._expect_ack("RCACK", "CLCKT"),
            timeout=3.0,
        )

    async def unlock_timer(self, timer_id: int) -> None:
        # R,CUNLT,<val> -> R,RCACK,CUNLT
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CUNLT", timer_id),
            expect=self._expect_ack("RCACK", "CUNLT"),
            timeout=3.0,
        )

    async def set_global(self, address: int, value: int) -> None:
        # R,CSETG,address,value -> R,RCACK,CSETG
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CSETG", address, value),
            expect=self._expect_ack("RCACK", "CSETG"),
            timeout=3.0,
        )

    async def get_global(self, address: int) -> int:
        # R,CGETG,address -> R,RQRES,CGETG,<value>
        t = self._pick_cmd_transport()
        resp = await t.request(
            self._cmd("R", "CGETG", address),
            expect=self._expect_query("CGETG"),
            timeout=3.0,
        )
        return int(resp.fields[0]) if resp.fields else 0

    async def increment_load_levels(self, load_group_id: int, value: int) -> None:
        # R,CUPLL,<loadgroupid>,<value> -> R,RCACK,CUPLL
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CUPLL", load_group_id, value),
            expect=self._expect_ack("RCACK", "CUPLL"),
            timeout=3.0,
        )

    async def decrement_load_levels(self, load_group_id: int, value: int) -> None:
        # R,CDNLL,<loadgroupid>,<value> -> R,RCACK,CDNLL
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CDNLL", load_group_id, value),
            expect=self._expect_ack("RCACK", "CDNLL"),
            timeout=3.0,
        )

    async def initialize_load_levels(self, load_group_id: int, value: int) -> None:
        # R,CINLL,<loadgroupid>,<value> -> R,RCACK,CINLL
        t = self._pick_cmd_transport()
        await t.request(
            self._cmd("R", "CINLL", load_group_id, value),
            expect=self._expect_ack("RCACK", "CINLL"),
            timeout=3.0,
        )
