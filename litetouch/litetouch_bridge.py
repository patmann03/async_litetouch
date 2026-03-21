from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Callable

from .litetouch_rtc import LiteTouchClient  # <-- your earlier class

_LOGGER = logging.getLogger(__name__)



# Helper functions
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
        default_transition: int = 3,
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

        bitmap_hex, levels = await self._client.get_module_levels(module_hex)  # DGMLV
        _LOGGER.debug(f"DGMLV Resp.  Bitmap Hex: {bitmap_hex}.  Levels: {levels}")

        # DGMLV returns up to 8; pad/truncate to exactly 8
        padded = list(levels[:8]) + [-1] * (8 - len(levels))

        # Apply bitmap: if bit says OFF, treat level as 0 (but preserve -1 unknown)
        bitmap_int = int(str(bitmap_hex), 16)

        # Configure this flag in your bridge __init__ as needed:
        # self._msb_first = True  # if output0 corresponds to bit7 (0x80)
        msb_first = getattr(self, "_msb_first", False)

        def bit_is_on(output_index: int) -> bool:
            """Check ON/OFF from bitmap for an output index 0..7."""
            if msb_first:
                # output0 -> bit7, output7 -> bit0
                bitpos = 7 - output_index
            else:
                # output0 -> bit0, output7 -> bit7
                bitpos = output_index
            return ((bitmap_int >> bitpos) & 1) == 1

        for i in range(8):
            if padded[i] < 0:
                continue  # keep unknowns
            if not bit_is_on(i):
                padded[i] = 0

        self._module_levels[module_int] = padded

    async def lt_toggle_switch(
        self,
        keypad: str,
    ) -> None:
        """Toggle litetouch button (like pressing the button)"""
        await self._client.toggle_switch(keypad)

    async def set_load_off(
        self,
        loadid: int,

    ) -> None:
        """Set load off - loadid of grouped loads"""
        # Set load off
        await self._client.set_loads_off(loadid)

    async def set_load_on(
        self,
        loadid: int,

    ) -> None:
        """Set load on - loadid of grouped loads"""
        # Set load on
        await self._client.set_loads_on(loadid)

    async def set_clock(
        self,
        clock,

        ) -> None:
        """Set controller clock to prevent drift"""
        # Set time on controller to prevent drift.
        await self._client.set_clock(clock)


    async def initialize_load_levels(
        self,
        loadid: int,
        level_pct: int,
        

    ) -> None:
        """Set the load level of the loadid brightness: 0...100"""
        
        await self._client.initialize_load_levels(loadid, level_pct)

    async def press_switch(self, ssso: str) -> None:
        """Press a keypad button (CPRSW)."""
        await self._client.press_switch(ssso)

    async def hold_switch(self, ssso: str) -> None:
        """Hold a keypad button (CHDSW)."""
        await self._client.hold_switch(ssso)

    async def release_switch(self, ssso: str) -> None:
        """Release a held keypad button (CRLSW)."""
        await self._client.release_switch(ssso)

    async def press_hold_switch(self, ssso: str) -> None:
        """Press and hold a keypad button (CPHSW)."""
        await self._client.press_hold_switch(ssso)

    async def set_led_on(self, ssso: str) -> None:
        """Turn on a keypad LED (CLDON)."""
        await self._client.set_led_on(ssso)

    async def set_led_off(self, ssso: str) -> None:
        """Turn off a keypad LED (CLDOF)."""
        await self._client.set_led_off(ssso)

    async def recall_load_preset(self, load_group: int) -> None:
        """Recall saved preset levels for a load group (CSLLV)."""
        await self._client.set_load_levels(load_group)

    async def restore_load_states(self, load_group: int) -> None:
        """Restore previous load states for a load group (CSPLS)."""
        await self._client.set_previous_load_states(load_group)

    async def open_loads(self, load_group: int) -> None:
        """Open relay loads in a load group (COPNL)."""
        await self._client.open_loads(load_group)

    async def close_loads(self, load_group: int) -> None:
        """Close relay loads in a load group (CCLSL)."""
        await self._client.close_loads(load_group)

    async def stop_loads(self, load_group: int) -> None:
        """Stop loads in a load group (CSTPL)."""
        await self._client.stop_loads(load_group)

    async def start_ramp(self, load_group: int) -> None:
        """Start ramping a load group (CSTRP)."""
        await self._client.start_ramp(load_group)

    async def stop_ramp(self, load_group: int) -> None:
        """Stop ramping a load group (CSPRP)."""
        await self._client.stop_ramp(load_group)

    async def start_ramp_to_min(self, load_group: int) -> None:
        """Ramp a load group to its minimum level (CSRMN)."""
        await self._client.start_ramp_to_min(load_group)

    async def start_ramp_to_max(self, load_group: int) -> None:
        """Ramp a load group to its maximum level (CSRMX)."""
        await self._client.start_ramp_to_max(load_group)

    async def lock_loads(self, load_group: int) -> None:
        """Lock a load group (CLCKL)."""
        await self._client.lock_loads(load_group)

    async def unlock_loads(self, load_group: int) -> None:
        """Unlock a load group (CUNLL)."""
        await self._client.unlock_loads(load_group)

    async def lock_switch(self, ssso: str) -> None:
        """Lock a keypad switch (CLCKS)."""
        await self._client.lock_switch(ssso)

    async def unlock_switch(self, ssso: str) -> None:
        """Unlock a keypad switch (CUNLS)."""
        await self._client.unlock_switch(ssso)

    async def lock_timer(self, timer_id: int) -> None:
        """Lock a timer (CLCKT)."""
        await self._client.lock_timer(timer_id)

    async def unlock_timer(self, timer_id: int) -> None:
        """Unlock a timer (CUNLT)."""
        await self._client.unlock_timer(timer_id)

    async def increment_load_levels(self, load_group: int, step: int) -> None:
        """Increment load group brightness by a step amount (CUPLL)."""
        await self._client.increment_load_levels(load_group, step)

    async def decrement_load_levels(self, load_group: int, step: int) -> None:
        """Decrement load group brightness by a step amount (CDNLL)."""
        await self._client.decrement_load_levels(load_group, step)

    async def set_global(self, address: int, value: int) -> None:
        """Set a controller global variable (CSETG)."""
        await self._client.set_global(address, value)

    async def save_load_preset(self, load_group: int) -> None:
        """Copy current levels to preset for a load group (CGCLV)."""
        await self._client.copy_current_to_preset_levels(load_group)

    # ---- push handler ----

    async def set_output_level(
        self,
        module_hex: str,
        output: int,
        level_pct: int,
        loadid: Optional[int] = None,
        transition: Optional[int] = None,
    ) -> None:
        """
        Uses DSMLV to set one output without sending all 8 levels.

        DSMLV is sparse: the bitmap indicates which outputs are included, and only those
        levels should be sent (in bit order). Other outputs are left unchanged by the device.
        """
        module_int = int(module_hex, 16)
        transition = self._default_transition if transition is None else transition

        _LOGGER.debug("module int: %s  module_hex %s", module_int, module_hex)

        # Ensure we have a cached view (for HA state tracking)
        await self.ensure_module_cached(module_hex)

        # Clamp & apply to cached copy
        current = self._module_levels.get(module_int, [-1] * 8)
        _LOGGER.debug("current levels: %s, output (socket#): %s", current, output)

        new_levels = list(current)
        new_levels[output] = max(0, min(100, int(level_pct)))
        _LOGGER.debug("new levels: %s", new_levels)

        # Bitmap that selects which outputs we are sending
        bitmap_hex = bitmask_for_output(output)
        _LOGGER.debug("bitmap_hex: %s", bitmap_hex)

        # Build sparse payload: only levels for bits set in bitmap
        mask = int(bitmap_hex, 16)
        levels_to_send: list[int] = []

        # For 8 outputs, pack values in increasing bit order (bit0..bit7)
        # (This matches the common DSMLV convention where 0x40 -> output 6.)
        for i in range(8):
            if mask & (1 << i):
                lvl = new_levels[i]
                # If cache is uninitialized (-1) for any selected output, default safely
                if lvl < 0:
                    lvl = 0
                levels_to_send.append(int(lvl))

        _LOGGER.debug("levels_to_send (sparse): %s", levels_to_send)

        # Update cache now that we intend to set it (keeps HA state consistent)
        self._module_levels[module_int] = new_levels

        # Send only the selected levels; do NOT send all 8
        await self._client.set_module_levels(
            module_hex,
            bitmap_hex,
            int(transition),
            levels_to_send,
        )

        # optimistic update (controller should also push RMODU)
        # self._module_levels[module_int] = new_levels
        # for cb in list(self._listeners):
        #     cb(module_int)

    # ---- push handler ----

    def _on_module_update(
        self, module_int: int, changed_map: str, levels: List[int]
    ) -> None:
        # Per protocol, RMODU includes level1..level8 and notes mask is FF in this implementation. [1](https://developers.home-assistant.io/docs/creating_integration_manifest/)
        padded = list(levels[:8]) + [-1] * (8 - len(levels))
        self._module_levels[module_int] = padded

        for cb in list(self._listeners):
            cb(module_int)
