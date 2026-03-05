from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Callable

from .litetouch_rtc import LiteTouchClient  # <-- your earlier class

_LOGGER = logging.getLogger(__name__)


def pct_to_ha(level_0_100: int) -> int:
    """Convert LiteTouch 0..100 to HA 1..255."""
    if level_0_100 <= 0:
        return 0
    return max(1, min(255, round(level_0_100 * 255 / 100)))


def ha_to_pct(brightness_0_255: int) -> int:
    """Convert HA 0..255 to LiteTouch 0..100."""
    if brightness_0_255 <= 0:
        return 0
    return max(1, min(100, round(brightness_0_255 * 100 / 255)))


def bitmask_for_output(output: int) -> str:
    """
    Create a hex bitmap for one output (0..7).
    Assumes output 0 corresponds to bit 0 (LSB).
    """
    mask = 1 << output
    return f"{mask:02X}"


class LiteTouchBridge:
    """
    Owns LiteTouchClient, maintains module level cache, and fans out push updates.

    Push source:
      R,RMODU,<moduleHex>,<map>,level1..level8  (notification) [1](https://developers.home-assistant.io/docs/creating_integration_manifest/)
    Write command:
      R,DSMLV,<mmm>,<map>,<time>,<level1>..<level8  (ack RDACK) [1](https://developers.home-assistant.io/docs/creating_integration_manifest/)
    """

    def __init__(
        self,
        host: str,
        port: int,
        command_connections: int = 4,
        event_connection: bool = True,
        default_transition: int = 1,
    ) -> None:
        self._client = LiteTouchClient(
            host,
            port,
            command_connections=command_connections,
            use_separate_event_connection=event_connection,
            print_raw=False,
        )

        self._default_transition = default_transition

        # module_int -> list of 8 levels (0..100, -1 for unknown)
        self._module_levels: Dict[int, List[int]] = {}

        # callbacks: called when a module updates
        self._listeners: List[Callable[[int], None]] = []

        # hook push updates
        self._client.on_module_update = self._on_module_update

        # internal guard for cache refresh per module
        self._locks: Dict[int, asyncio.Lock] = {}

    async def start(self) -> None:
        await self._client.start()
        # Enable module notifications (you can call set_module_notify per module from entities)
        # and/or enable internal events as needed:
        # await self._client.set_internal_event_notify(7)  # optional [1](https://developers.home-assistant.io/docs/creating_integration_manifest/)

    async def stop(self) -> None:
        await self._client.close()

    def add_listener(self, cb: Callable[[int], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    def get_output_level_pct(self, module_int: int, output: int) -> Optional[int]:
        levels = self._module_levels.get(module_int)
        if not levels or output < 0 or output > 7:
            return None
        val = levels[output]
        if val < 0:
            return None
        return val

    async def ensure_module_notify(self, module_hex: str) -> None:
        """Enable SMODN notifications for module (mode=1). [1](https://developers.home-assistant.io/docs/creating_integration_manifest/)"""
        await self._client.set_module_notify(module_hex, 1)

    async def ensure_module_cached(self, module_hex: str) -> None:
        """
        If we don't have levels yet, query DGMLV to seed cache. [1](https://developers.home-assistant.io/docs/creating_integration_manifest/)
        """
        module_int = int(module_hex, 16)
        lock = self._locks.setdefault(module_int, asyncio.Lock())

        async with lock:
            if module_int in self._module_levels and any(
                x >= 0 for x in self._module_levels[module_int]
            ):
                return

            bitmap, levels = await self._client.get_module_levels(
                module_hex
            )  # DGMLV [1](https://developers.home-assistant.io/docs/creating_integration_manifest/)
            # DGMLV returns up to 8; pad to 8 with -1
            padded = list(levels[:8]) + [-1] * (8 - len(levels))
            self._module_levels[module_int] = padded

    async def lt_toggle_switch(
        self,
        keypad: str,
    ) -> None:
        await self._client.toggle_switch(keypad)

    async def set_load_off(
        self,
        module_hex: str,
        output: int,
        level_pct: int,
        loadid: int,
        transition: Optional[int] = None,
    ) -> None:

        module_int = int(module_hex, 16)
        transition = self._default_transition if transition is None else transition
        _LOGGER.debug(f"module int: {module_int}  module_hex {module_hex}")
        await self.ensure_module_cached(module_hex)

        # Clone cached levels
        current = self._module_levels.get(module_int, [-1] * 8)
        _LOGGER.debug(
            f"current levels: {current}, output value (module socket#): {output}"
        )
        new_levels = list(current)
        new_levels[output] = max(0, min(100, int(level_pct)))
        _LOGGER.debug(f"new levels: {new_levels}")

        bitmap_hex = bitmask_for_output(output)

        _LOGGER.debug(f"bitmap_hex: {bitmap_hex}")

        # Send DSMLV with all 8 levels so we don't accidentally change others
        await self._client.set_loads_off(loadid)

        # optimistic update (controller should also push RMODU)
        self._module_levels[module_int] = new_levels
        for cb in list(self._listeners):
            cb(module_int)

    # ---- push handler ----

    async def set_output_level(
        self,
        module_hex: str,
        output: int,
        level_pct: int,
        loadid: int,
        transition: Optional[int] = None,
    ) -> None:
        """
        Uses DSMLV to set one output while preserving other outputs from cache. [1](https://developers.home-assistant.io/docs/creating_integration_manifest)
        """
        module_int = int(module_hex, 16)
        transition = self._default_transition if transition is None else transition
        _LOGGER.debug(f"module int: {module_int}  module_hex {module_hex}")
        await self.ensure_module_cached(module_hex)

        # Clone cached levels
        current = self._module_levels.get(module_int, [-1] * 8)
        _LOGGER.debug(
            f"current levels: {current}, output value (module socket#): {output}"
        )
        new_levels = list(current)
        new_levels[output] = max(0, min(100, int(level_pct)))
        _LOGGER.debug(f"new levels: {new_levels}")

        bitmap_hex = bitmask_for_output(output)

        _LOGGER.debug(f"bitmap_hex: {bitmap_hex}")

        # Send DSMLV with all 8 levels so we don't accidentally change others
        await self._client.initialize_load_levels(loadid, level_pct)
        # await self._client.set_module_levels(
        #     module_hex, bitmap_hex, int(transition), new_levels
        # )

        # optimistic update (controller should also push RMODU)
        self._module_levels[module_int] = new_levels
        for cb in list(self._listeners):
            cb(module_int)

    # ---- push handler ----

    def _on_module_update(
        self, module_int: int, changed_map: str, levels: List[int]
    ) -> None:
        # Per protocol, RMODU includes level1..level8 and notes mask is FF in this implementation. [1](https://developers.home-assistant.io/docs/creating_integration_manifest/)
        padded = list(levels[:8]) + [-1] * (8 - len(levels))
        self._module_levels[module_int] = padded

        for cb in list(self._listeners):
            cb(module_int)
