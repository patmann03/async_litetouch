"""Tests for litetouch/litetouch_rtc.py — protocol parsing, transport, and client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from litetouch.litetouch_rtc import (
    LiteTouchClient,
    LiteTouchMessage,
    LiteTouchResponse,
    _LiteTouchTransport,
    _int_auto,
    _parse_line,
    _to_response,
)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


class TestIntAuto:
    def test_decimal(self):
        assert _int_auto("100") == 100

    def test_zero(self):
        assert _int_auto("0") == 0

    def test_hex_uppercase(self):
        assert _int_auto("FF") == 255

    def test_hex_lowercase(self):
        assert _int_auto("0a") == 10

    def test_hex_no_prefix(self):
        assert _int_auto("1A") == 26

    def test_negative(self):
        assert _int_auto("-1") == -1

    def test_strips_whitespace(self):
        assert _int_auto(" 50 ") == 50


class TestParseLine:
    def test_basic_split(self):
        msg = _parse_line("R,RCACK,DSMLV\r")
        assert msg.parts == ("R", "RCACK", "DSMLV")

    def test_strips_cr(self):
        msg = _parse_line("R,RMODU,07\r")
        assert "\r" not in msg.raw

    def test_strips_crlf(self):
        msg = _parse_line("R,RCACK,DSMLV\r\n")
        assert msg.parts == ("R", "RCACK", "DSMLV")

    def test_raw_preserved(self):
        msg = _parse_line("R,RCACK,DSMLV\r")
        assert "R,RCACK,DSMLV" in msg.raw

    def test_multiple_fields(self):
        msg = _parse_line("R,RMODU,07,FF,50,75,0,0,0,0,0,0\r")
        assert msg.parts[0] == "R"
        assert msg.parts[1] == "RMODU"
        assert msg.parts[2] == "07"


class TestToResponse:
    def _msg(self, line: str) -> LiteTouchMessage:
        return _parse_line(line)

    def test_rcack(self):
        resp = _to_response(self._msg("R,RCACK,DSMLV\r"))
        assert resp.kind == "RCACK"
        assert resp.cmd == "DSMLV"
        assert resp.fields == ()

    def test_rdack(self):
        resp = _to_response(self._msg("R,RDACK,DSMLV\r"))
        assert resp.kind == "RDACK"
        assert resp.cmd == "DSMLV"

    def test_rqres(self):
        resp = _to_response(self._msg("R,RQRES,DGMLV,FF,50,75\r"))
        assert resp.kind == "RQRES"
        assert resp.cmd == "DGMLV"
        assert resp.fields == ("FF", "50", "75")

    def test_rmodu_no_cmd(self):
        resp = _to_response(self._msg("R,RMODU,07,FF,50,75\r"))
        assert resp.kind == "RMODU"
        assert resp.cmd is None
        assert resp.fields == ("07", "FF", "50", "75")

    def test_rledu(self):
        resp = _to_response(self._msg("R,RLEDU,0001,A0\r"))
        assert resp.kind == "RLEDU"
        assert resp.cmd is None
        assert resp.fields == ("0001", "A0")

    def test_revnt(self):
        resp = _to_response(self._msg("R,REVNT,SWP,12\r"))
        assert resp.kind == "REVNT"
        assert resp.fields == ("SWP", "12")

    def test_unknown_non_r_prefix(self):
        resp = _to_response(self._msg("X,FOO,BAR\r"))
        assert resp.kind == "NONSTANDARD"

    def test_nonstandard_single_field(self):
        msg = LiteTouchMessage(raw="ONLYONE", parts=("ONLYONE",))
        resp = _to_response(msg)
        assert resp.kind == "UNKNOWN"

    def test_rcack_with_extra_fields(self):
        resp = _to_response(self._msg("R,RCACK,SIEVN,extra\r"))
        assert resp.kind == "RCACK"
        assert resp.cmd == "SIEVN"
        assert resp.fields == ("extra",)


# ---------------------------------------------------------------------------
# _LiteTouchTransport — connect / disconnect / callbacks
# ---------------------------------------------------------------------------


class TestTransportConnectDisconnect:
    def _make_transport(self, **kwargs) -> _LiteTouchTransport:
        defaults = dict(keepalive_interval=0, send_delay_ms=0)
        defaults.update(kwargs)
        return _LiteTouchTransport("test", "10.0.0.1", 10001, **defaults)

    def _mock_writer(self) -> MagicMock:
        w = MagicMock(spec=asyncio.StreamWriter)
        w.is_closing.return_value = False
        w.write = MagicMock()
        w.drain = AsyncMock()
        w.close = MagicMock()
        w.wait_closed = AsyncMock()
        return w

    def _mock_reader(self) -> AsyncMock:
        r = AsyncMock(spec=asyncio.StreamReader)
        return r

    def test_not_connected_initially(self):
        t = self._make_transport()
        assert t.is_connected is False

    async def test_connect_sets_is_connected(self):
        t = self._make_transport()
        r, w = self._mock_reader(), self._mock_writer()
        with patch("asyncio.open_connection", return_value=(r, w)):
            await t._connect()
        assert t.is_connected is True

    async def test_connect_sends_sievn(self):
        t = self._make_transport()
        r, w = self._mock_reader(), self._mock_writer()
        with patch("asyncio.open_connection", return_value=(r, w)):
            await t._connect()
        written = b"".join(call.args[0] for call in w.write.call_args_list)
        assert b"SIEVN" in written

    async def test_connect_fires_on_connection_change_true(self):
        t = self._make_transport()
        fired = []
        t.on_connection_change = lambda c: fired.append(c)
        r, w = self._mock_reader(), self._mock_writer()
        with patch("asyncio.open_connection", return_value=(r, w)):
            await t._connect()
        assert fired == [True]

    async def test_disconnect_fires_on_connection_change_false(self):
        t = self._make_transport()
        fired = []
        t.on_connection_change = lambda c: fired.append(c)
        t._writer = self._mock_writer()  # simulate already connected
        t._reader = self._mock_reader()
        await t._disconnect()
        assert False in fired

    async def test_disconnect_no_callback_if_not_connected(self):
        t = self._make_transport()
        fired = []
        t.on_connection_change = lambda c: fired.append(c)
        # _writer is None → was_connected = False
        await t._disconnect()
        assert fired == []

    async def test_disconnect_clears_reader_writer(self):
        t = self._make_transport()
        t._writer = self._mock_writer()
        t._reader = self._mock_reader()
        await t._disconnect()
        assert t._writer is None
        assert t._reader is None


# ---------------------------------------------------------------------------
# _LiteTouchTransport — send
# ---------------------------------------------------------------------------


class TestTransportSend:
    def _connected_transport(self) -> tuple[_LiteTouchTransport, MagicMock]:
        t = _LiteTouchTransport(
            "test", "10.0.0.1", 10001, keepalive_interval=0, send_delay_ms=0
        )
        w = MagicMock(spec=asyncio.StreamWriter)
        w.is_closing.return_value = False
        w.write = MagicMock()
        w.drain = AsyncMock()
        t._writer = w
        return t, w

    async def test_send_appends_cr(self):
        t, w = self._connected_transport()
        await t.send("R,FOO")
        w.write.assert_called_once()
        data = w.write.call_args[0][0]
        assert data.endswith(b"\r")

    async def test_send_encodes_ascii(self):
        t, w = self._connected_transport()
        await t.send("R,DGCLK")
        data = w.write.call_args[0][0]
        assert isinstance(data, bytes)
        assert b"R,DGCLK" in data

    async def test_send_does_not_double_cr(self):
        t, w = self._connected_transport()
        await t.send("R,FOO\r")
        data = w.write.call_args[0][0]
        assert data.count(b"\r") == 1


# ---------------------------------------------------------------------------
# _LiteTouchTransport — request / waiter matching
# ---------------------------------------------------------------------------


class TestTransportRequest:
    def _connected_transport(self) -> _LiteTouchTransport:
        t = _LiteTouchTransport(
            "test", "10.0.0.1", 10001, keepalive_interval=0, send_delay_ms=0
        )
        w = MagicMock(spec=asyncio.StreamWriter)
        w.is_closing.return_value = False
        w.write = MagicMock()
        w.drain = AsyncMock()
        t._writer = w
        return t

    async def test_request_resolves_on_matching_response(self):
        t = self._connected_transport()

        async def _resolve():
            await asyncio.sleep(0.01)
            resp = LiteTouchResponse(
                raw="R,RDACK,DSMLV", kind="RDACK", cmd="DSMLV", fields=()
            )
            for matcher, fut in list(t._waiters):
                if not fut.done() and matcher(resp):
                    fut.set_result(resp)
                    break

        asyncio.create_task(_resolve())
        result = await t.request(
            "R,DSMLV,0007,01,3,50",
            expect=lambda r: r.kind == "RDACK" and r.cmd == "DSMLV",
            timeout=2.0,
        )
        assert result.kind == "RDACK"
        assert result.cmd == "DSMLV"

    async def test_request_timeout_raises(self):
        t = self._connected_transport()
        with pytest.raises(asyncio.TimeoutError):
            await t.request(
                "R,DGCLK",
                expect=lambda r: r.kind == "RQRES",
                timeout=0.05,
            )

    async def test_request_removes_waiter_on_timeout(self):
        t = self._connected_transport()
        try:
            await t.request("R,DGCLK", expect=lambda r: False, timeout=0.05)
        except asyncio.TimeoutError:
            pass
        assert len(t._waiters) == 0

    async def test_close_cancels_pending_waiters(self):
        t = self._connected_transport()

        # Inject a waiter manually
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        t._waiters.append((lambda r: False, fut))

        await t.close()
        assert fut.cancelled()


# ---------------------------------------------------------------------------
# _LiteTouchTransport — connection error instead of assert
# ---------------------------------------------------------------------------


class TestTransportConnectionErrors:
    async def test_run_raises_connection_error_if_reader_none_after_connect(self):
        """After _connect succeeds, _reader must not be None; otherwise ConnectionError."""
        t = _LiteTouchTransport(
            "test", "10.0.0.1", 10001,
            keepalive_interval=0, send_delay_ms=0, reconnect=False,
        )
        t._stop.set()  # stop after first iteration

        w = MagicMock(spec=asyncio.StreamWriter)
        w.is_closing.return_value = False
        w.write = MagicMock()
        w.drain = AsyncMock()

        async def fake_connect(host, port):
            t._writer = w
            t._reader = None  # simulate broken state
            return None, None  # not used; we set manually above

        with patch("asyncio.open_connection", side_effect=fake_connect):
            # _run should encounter reader=None and raise ConnectionError
            # which it catches and breaks out
            await t._run()


# ---------------------------------------------------------------------------
# LiteTouchClient — round-robin and unsolicited dispatch
# ---------------------------------------------------------------------------


class TestClientRoundRobin:
    def test_picks_transports_in_order(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=2,
            use_separate_event_connection=False,
        )
        t0 = client._cmd_transports[0]
        t1 = client._cmd_transports[1]
        assert client._pick_cmd_transport() is t0
        assert client._pick_cmd_transport() is t1
        assert client._pick_cmd_transport() is t0  # wraps around

    def test_single_transport_always_same(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=1,
            use_separate_event_connection=False,
        )
        t = client._cmd_transports[0]
        for _ in range(5):
            assert client._pick_cmd_transport() is t


class TestClientUnsolicitedDispatch:
    def _client(self) -> LiteTouchClient:
        return LiteTouchClient(
            "10.0.0.1", 10001, command_connections=1,
            use_separate_event_connection=False,
        )

    def test_rmodu_fires_on_module_update(self):
        client = self._client()
        updates: list = []
        client.on_module_update = lambda mod, bmap, lvls: updates.append((mod, bmap, lvls))

        resp = LiteTouchResponse(
            raw="R,RMODU,07,FF,50,75,0,0,0,0,0,0",
            kind="RMODU",
            cmd=None,
            fields=("07", "FF", "50", "75", "0", "0", "0", "0", "0", "0"),
        )
        client._handle_unsolicited(resp)

        assert len(updates) == 1
        assert updates[0][0] == 7  # int(0x07)
        assert updates[0][1] == "FF"
        assert updates[0][2] == [50, 75, 0, 0, 0, 0, 0, 0]

    def test_rmodu_not_fired_if_too_few_fields(self):
        client = self._client()
        called = []
        client.on_module_update = lambda *a: called.append(a)

        resp = LiteTouchResponse(
            raw="R,RMODU,07,FF", kind="RMODU", cmd=None, fields=("07", "FF")
        )
        client._handle_unsolicited(resp)
        assert called == []

    def test_rledu_fires_on_led_update(self):
        client = self._client()
        updates: list = []
        client.on_led_update = lambda s, b: updates.append((s, b))

        resp = LiteTouchResponse(
            raw="R,RLEDU,001,A0", kind="RLEDU", cmd=None, fields=("001", "A0")
        )
        client._handle_unsolicited(resp)
        assert updates == [("001", "A0")]

    def test_revnt_fires_on_event(self):
        client = self._client()
        events: list = []
        client.on_event = lambda t, v: events.append((t, v))

        resp = LiteTouchResponse(
            raw="R,REVNT,SWP,5", kind="REVNT", cmd=None, fields=("SWP", "5")
        )
        client._handle_unsolicited(resp)
        assert events == [("SWP", "5")]

    def test_on_any_message_called_for_all(self):
        client = self._client()
        all_msgs: list = []
        client.on_any_message = lambda r: all_msgs.append(r)

        for kind in ("RMODU", "RLEDU", "REVNT", "RCACK"):
            fields = ("07", "FF", "50") if kind == "RMODU" else ("a", "b")
            resp = LiteTouchResponse(raw="", kind=kind, cmd=None, fields=fields)
            client._handle_unsolicited(resp)

        assert len(all_msgs) == 4


class TestClientConnectionChange:
    def test_connection_change_propagates_to_callback(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=1,
            use_separate_event_connection=False,
        )
        changes: list = []
        client.on_connection_change = lambda c: changes.append(c)

        # Simulate the primary transport firing its callback
        client._cmd_transports[0].on_connection_change(True)
        assert changes == [True]

        client._cmd_transports[0].on_connection_change(False)
        assert changes == [True, False]

    def test_event_transport_is_primary_when_present(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=2,
            use_separate_event_connection=True,
        )
        # event transport should have the connection callback wired
        assert client._event_transport is not None
        assert client._event_transport.on_connection_change == client._handle_connection_change
        # cmd transports should NOT
        for t in client._cmd_transports:
            assert t.on_connection_change is None

    def test_cmd_transport_is_primary_when_no_event(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=2,
            use_separate_event_connection=False,
        )
        assert client._cmd_transports[0].on_connection_change == client._handle_connection_change
        assert client._cmd_transports[1].on_connection_change is None


class TestClientLifecycle:
    async def test_start_starts_all_transports(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=2,
            use_separate_event_connection=True,
        )
        for t in client._cmd_transports:
            t.start = AsyncMock()
        client._event_transport.start = AsyncMock()

        await client.start()

        for t in client._cmd_transports:
            t.start.assert_awaited_once()
        client._event_transport.start.assert_awaited_once()

    async def test_close_closes_all_transports(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=2,
            use_separate_event_connection=True,
        )
        for t in client._cmd_transports:
            t.close = AsyncMock()
        client._event_transport.close = AsyncMock()

        await client.close()

        for t in client._cmd_transports:
            t.close.assert_awaited_once()
        client._event_transport.close.assert_awaited_once()


class TestClientGetModuleLevels:
    async def test_parses_bitmap_and_levels(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=1,
            use_separate_event_connection=False,
        )
        resp = LiteTouchResponse(
            raw="R,RQRES,DGMLV,0007,FF,50,75,0,0,0,0,0,0",
            kind="RQRES",
            cmd="DGMLV",
            fields=("0007", "FF", "50", "75", "0", "0", "0", "0", "0", "0"),
        )
        client._cmd_transports[0].request = AsyncMock(return_value=resp)

        bitmap, levels = await client.get_module_levels("0007")
        assert bitmap == "FF"
        assert levels == [50, 75, 0, 0, 0, 0, 0, 0]

    async def test_parses_hex_levels(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=1,
            use_separate_event_connection=False,
        )
        resp = LiteTouchResponse(
            raw="",
            kind="RQRES",
            cmd="DGMLV",
            fields=("0007", "FF", "1A", "4B"),  # 0x1A=26, 0x4B=75 (both fail decimal)
        )
        client._cmd_transports[0].request = AsyncMock(return_value=resp)

        bitmap, levels = await client.get_module_levels("0007")
        assert 26 in levels   # 0x1A
        assert 75 in levels   # 0x4B

    async def test_empty_fields_returns_defaults(self):
        client = LiteTouchClient(
            "10.0.0.1", 10001, command_connections=1,
            use_separate_event_connection=False,
        )
        resp = LiteTouchResponse(raw="", kind="RQRES", cmd="DGMLV", fields=())
        client._cmd_transports[0].request = AsyncMock(return_value=resp)

        bitmap, levels = await client.get_module_levels("0007")
        assert bitmap == ""
        assert levels == []
