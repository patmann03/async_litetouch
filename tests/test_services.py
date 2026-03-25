"""Tests for litetouch/services.py — HA service handlers and async_unload_services."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from litetouch.services import (
    ALL_SERVICES,
    DOMAIN,
    async_setup_services,
    async_unload_services,
)


# ---------------------------------------------------------------------------
# Helper: capture registered service handlers
# ---------------------------------------------------------------------------


def _setup_and_capture(mock_hass, mock_bridge):
    """Call async_setup_services and return a dict of {service_name: handler}."""
    handlers = {}

    def capture_register(domain, service_name, handler, schema=None):
        handlers[service_name] = handler

    mock_hass.services.async_register = MagicMock(side_effect=capture_register)
    async_setup_services(mock_hass, mock_bridge)
    return handlers


def _call(service_name, data=None):
    """Make a minimal ServiceCall-like object."""
    call_obj = MagicMock()
    call_obj.service = service_name
    call_obj.data = data or {}
    return call_obj


# ---------------------------------------------------------------------------
# async_unload_services
# ---------------------------------------------------------------------------


class TestUnloadServices:
    def test_removes_all_services(self, mock_hass):
        async_unload_services(mock_hass)
        removed = {c.args[1] for c in mock_hass.services.async_remove.call_args_list}
        for svc in ALL_SERVICES:
            assert svc in removed, f"Service {svc} was not removed"

    def test_all_services_list_is_not_empty(self):
        assert len(ALL_SERVICES) > 0

    def test_all_services_list_coverage(self):
        # Spot-check a few key entries
        assert "set_module_levels" in ALL_SERVICES
        assert "toggle_switch" in ALL_SERVICES
        assert "set_load_on" in ALL_SERVICES
        assert "set_global" in ALL_SERVICES


# ---------------------------------------------------------------------------
# Service handler: set_module_levels (calls bridge.set_module_levels now)
# ---------------------------------------------------------------------------


class TestSetModuleLevels:
    async def test_calls_bridge_set_module_levels(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("set_module_levels", {
            "module": "0007", "bitmap": "FF", "ramp": 3, "levels": [50, 75]
        })
        await handlers["set_module_levels"](sc)
        mock_bridge.set_module_levels.assert_awaited_once_with("0007", "FF", 3, [50, 75])


# ---------------------------------------------------------------------------
# Service handler: toggle_switch
# ---------------------------------------------------------------------------


class TestToggleSwitch:
    async def test_calls_lt_toggle_switch(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("toggle_switch", {"switch": "0001001"})
        await handlers["toggle_switch"](sc)
        mock_bridge.lt_toggle_switch.assert_awaited_once_with("0001001")


# ---------------------------------------------------------------------------
# Service handler: set_load_on / set_load_off
# ---------------------------------------------------------------------------


class TestLoadOnOff:
    async def test_set_load_on(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("set_load_on", {"loadid": 5})
        await handlers["set_load_on"](sc)
        mock_bridge.set_load_on.assert_awaited_once_with(5)

    async def test_set_load_off(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("set_load_off", {"loadid": 5})
        await handlers["set_load_off"](sc)
        mock_bridge.set_load_off.assert_awaited_once_with(5)


# ---------------------------------------------------------------------------
# Service handler: set_load_level
# ---------------------------------------------------------------------------


class TestSetLoadLevel:
    async def test_calls_initialize_load_levels(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("set_load_level", {"loadid": 3, "brightness_level": 75})
        await handlers["set_load_level"](sc)
        mock_bridge.initialize_load_levels.assert_awaited_once_with(3, 75)


# ---------------------------------------------------------------------------
# Service handlers: switch press/hold/release/press_hold
# ---------------------------------------------------------------------------


class TestSwitchActions:
    async def test_press_switch(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("press_switch", {"switch": "0001001"})
        await handlers["press_switch"](sc)
        mock_bridge.press_switch.assert_awaited_once_with("0001001")

    async def test_hold_switch(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("hold_switch", {"switch": "0001001"})
        await handlers["hold_switch"](sc)
        mock_bridge.hold_switch.assert_awaited_once_with("0001001")

    async def test_release_switch(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("release_switch", {"switch": "0001001"})
        await handlers["release_switch"](sc)
        mock_bridge.release_switch.assert_awaited_once_with("0001001")

    async def test_press_hold_switch(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("press_hold_switch", {"switch": "0001001"})
        await handlers["press_hold_switch"](sc)
        mock_bridge.press_hold_switch.assert_awaited_once_with("0001001")


# ---------------------------------------------------------------------------
# Service handlers: LED on/off
# ---------------------------------------------------------------------------


class TestLedActions:
    async def test_set_led_on(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("set_led_on", {"switch": "0001001"})
        await handlers["set_led_on"](sc)
        mock_bridge.set_led_on.assert_awaited_once_with("0001001")

    async def test_set_led_off(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("set_led_off", {"switch": "0001001"})
        await handlers["set_led_off"](sc)
        mock_bridge.set_led_off.assert_awaited_once_with("0001001")


# ---------------------------------------------------------------------------
# Service handlers: load presets and states
# ---------------------------------------------------------------------------


class TestLoadPresets:
    async def test_recall_load_preset(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("recall_load_preset", {"loadid": 2})
        await handlers["recall_load_preset"](sc)
        mock_bridge.recall_load_preset.assert_awaited_once_with(2)

    async def test_restore_load_states(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("restore_load_states", {"loadid": 2})
        await handlers["restore_load_states"](sc)
        mock_bridge.restore_load_states.assert_awaited_once_with(2)

    async def test_save_load_preset(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("save_load_preset", {"loadid": 2})
        await handlers["save_load_preset"](sc)
        mock_bridge.save_load_preset.assert_awaited_once_with(2)


# ---------------------------------------------------------------------------
# Service handlers: relay loads
# ---------------------------------------------------------------------------


class TestRelayLoads:
    async def test_open_loads(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("open_loads", {"loadid": 4})
        await handlers["open_loads"](sc)
        mock_bridge.open_loads.assert_awaited_once_with(4)

    async def test_close_loads(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("close_loads", {"loadid": 4})
        await handlers["close_loads"](sc)
        mock_bridge.close_loads.assert_awaited_once_with(4)

    async def test_stop_loads(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("stop_loads", {"loadid": 4})
        await handlers["stop_loads"](sc)
        mock_bridge.stop_loads.assert_awaited_once_with(4)


# ---------------------------------------------------------------------------
# Service handlers: ramping
# ---------------------------------------------------------------------------


class TestRampActions:
    async def test_start_ramp(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("start_ramp", {"loadid": 1})
        await handlers["start_ramp"](sc)
        mock_bridge.start_ramp.assert_awaited_once_with(1)

    async def test_stop_ramp(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("stop_ramp", {"loadid": 1})
        await handlers["stop_ramp"](sc)
        mock_bridge.stop_ramp.assert_awaited_once_with(1)

    async def test_ramp_to_min(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("ramp_to_min", {"loadid": 1})
        await handlers["ramp_to_min"](sc)
        mock_bridge.start_ramp_to_min.assert_awaited_once_with(1)

    async def test_ramp_to_max(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("ramp_to_max", {"loadid": 1})
        await handlers["ramp_to_max"](sc)
        mock_bridge.start_ramp_to_max.assert_awaited_once_with(1)


# ---------------------------------------------------------------------------
# Service handlers: lock/unlock
# ---------------------------------------------------------------------------


class TestLockUnlock:
    async def test_lock_loads(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("lock_loads", {"loadid": 1})
        await handlers["lock_loads"](sc)
        mock_bridge.lock_loads.assert_awaited_once_with(1)

    async def test_unlock_loads(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("unlock_loads", {"loadid": 1})
        await handlers["unlock_loads"](sc)
        mock_bridge.unlock_loads.assert_awaited_once_with(1)

    async def test_lock_switch(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("lock_switch", {"switch": "0001001"})
        await handlers["lock_switch"](sc)
        mock_bridge.lock_switch.assert_awaited_once_with("0001001")

    async def test_unlock_switch(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("unlock_switch", {"switch": "0001001"})
        await handlers["unlock_switch"](sc)
        mock_bridge.unlock_switch.assert_awaited_once_with("0001001")

    async def test_lock_timer(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("lock_timer", {"timer_id": 2})
        await handlers["lock_timer"](sc)
        mock_bridge.lock_timer.assert_awaited_once_with(2)

    async def test_unlock_timer(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("unlock_timer", {"timer_id": 2})
        await handlers["unlock_timer"](sc)
        mock_bridge.unlock_timer.assert_awaited_once_with(2)


# ---------------------------------------------------------------------------
# Service handlers: level increment/decrement
# ---------------------------------------------------------------------------


class TestLevelAdjust:
    async def test_increment_load_levels(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("increment_load_levels", {"loadid": 1, "step": 10})
        await handlers["increment_load_levels"](sc)
        mock_bridge.increment_load_levels.assert_awaited_once_with(1, 10)

    async def test_decrement_load_levels(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("decrement_load_levels", {"loadid": 1, "step": 10})
        await handlers["decrement_load_levels"](sc)
        mock_bridge.decrement_load_levels.assert_awaited_once_with(1, 10)


# ---------------------------------------------------------------------------
# Service handler: set_global
# ---------------------------------------------------------------------------


class TestSetGlobal:
    async def test_calls_bridge_set_global(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("set_global", {"address": 10, "value": 42})
        await handlers["set_global"](sc)
        mock_bridge.set_global.assert_awaited_once_with(10, 42)


# ---------------------------------------------------------------------------
# Service handler: set_clock
# ---------------------------------------------------------------------------


class TestSetClock:
    async def test_calls_bridge_set_clock(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("set_clock", {})
        await handlers["set_clock"](sc)
        mock_bridge.set_clock.assert_awaited_once()
        # verify the argument looks like a datetime string
        clock_arg = mock_bridge.set_clock.call_args[0][0]
        assert len(clock_arg) == 14  # YYYYmmddHHMMSS
        assert clock_arg.isdigit()

    async def test_set_clock_writes_state(self, mock_hass, mock_bridge):
        handlers = _setup_and_capture(mock_hass, mock_bridge)
        sc = _call("set_clock", {})
        await handlers["set_clock"](sc)
        mock_hass.states.async_set.assert_called()
