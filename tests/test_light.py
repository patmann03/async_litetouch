"""Tests for litetouch/light/light.py — LiteTouchLightEntity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from litetouch.litetouch_bridge import ha_to_pct, pct_to_ha
from litetouch.light.light import LiteTouchLightEntity


def _make_entity(
    bridge,
    name: str = "Kitchen",
    module: str = "0007",
    output: int = 0,
    loadid: int | None = None,
    default_transition: int = 3,
) -> LiteTouchLightEntity:
    cfg = {"name": name, "module": module, "output": output}
    if loadid is not None:
        cfg["loadid"] = loadid
    return LiteTouchLightEntity(bridge, cfg, default_transition)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestLightInit:
    def test_stores_name(self, mock_bridge):
        entity = _make_entity(mock_bridge, name="Dining Room")
        assert entity.name == "Dining Room"

    def test_stores_module_and_output(self, mock_bridge):
        entity = _make_entity(mock_bridge, module="000A", output=3)
        assert entity._module_hex == "000A"
        assert entity._output == 3
        assert entity._module_int == int("000A", 16)

    def test_loadid_1based_converted_to_0based(self, mock_bridge):
        entity = _make_entity(mock_bridge, loadid=1)
        assert entity._loadid_config == 1
        assert entity._loadid == 0  # adjusted -1

    def test_loadid_3_becomes_2(self, mock_bridge):
        entity = _make_entity(mock_bridge, loadid=3)
        assert entity._loadid == 2

    def test_no_loadid_stays_none(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        assert entity._loadid is None

    def test_initial_state_off(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        assert entity.is_on is False
        assert entity.brightness == 0

    def test_should_poll_false(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        assert entity.should_poll is False

    def test_supported_features_has_transition(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        from homeassistant.components.light import LightEntityFeature
        assert entity.supported_features == LightEntityFeature.TRANSITION


class TestLightUniqueId:
    def test_unique_id_format(self, mock_bridge):
        entity = _make_entity(mock_bridge, module="0007", output=0)
        assert entity.unique_id == "litetouch_rtc.0007_0"

    def test_unique_id_varies_with_output(self, mock_bridge):
        e1 = _make_entity(mock_bridge, module="0007", output=0)
        e2 = _make_entity(mock_bridge, module="0007", output=1)
        assert e1.unique_id != e2.unique_id


# ---------------------------------------------------------------------------
# Availability (new in coffee branch)
# ---------------------------------------------------------------------------


class TestLightAvailability:
    def test_available_when_bridge_connected(self, mock_bridge):
        mock_bridge.connected = True
        entity = _make_entity(mock_bridge)
        assert entity.available is True

    def test_unavailable_when_bridge_disconnected(self, mock_bridge):
        mock_bridge.connected = False
        entity = _make_entity(mock_bridge)
        assert entity.available is False


# ---------------------------------------------------------------------------
# Lifecycle: async_added_to_hass / async_will_remove_from_hass
# ---------------------------------------------------------------------------


class TestLightLifecycle:
    async def test_async_added_enables_module_notify(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()
        mock_bridge.ensure_module_notify.assert_awaited_once_with("0007")

    async def test_async_added_caches_module(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()
        mock_bridge.ensure_module_cached.assert_awaited_once_with("0007")

    async def test_async_added_registers_module_listener(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()
        mock_bridge.add_listener.assert_called_once()

    async def test_async_added_registers_connection_listener(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()
        mock_bridge.add_connection_listener.assert_called_once()

    async def test_async_will_remove_unregisters_module_listener(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()

        # Listener should be registered
        assert len(mock_bridge._listeners) == 1

        await entity.async_will_remove_from_hass()

        # Listener should be removed from the list
        assert len(mock_bridge._listeners) == 0

    async def test_async_will_remove_unregisters_connection_listener(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()

        assert len(mock_bridge._conn_listeners) == 1

        await entity.async_will_remove_from_hass()

        assert len(mock_bridge._conn_listeners) == 0

    async def test_async_will_remove_clears_remove_fns(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()
        await entity.async_will_remove_from_hass()
        assert entity._remove_listener is None
        assert entity._remove_connection_listener is None


# ---------------------------------------------------------------------------
# State refresh
# ---------------------------------------------------------------------------


class TestLightStateRefresh:
    def test_refresh_sets_on_when_level_positive(self, mock_bridge):
        mock_bridge.get_output_level_pct.return_value = 75
        entity = _make_entity(mock_bridge)
        entity._refresh_from_cache()
        assert entity.is_on is True
        assert entity.brightness == pct_to_ha(75)

    def test_refresh_sets_off_when_level_zero(self, mock_bridge):
        mock_bridge.get_output_level_pct.return_value = 0
        entity = _make_entity(mock_bridge)
        entity._refresh_from_cache()
        assert entity.is_on is False

    def test_refresh_no_change_when_level_unknown(self, mock_bridge):
        mock_bridge.get_output_level_pct.return_value = None
        entity = _make_entity(mock_bridge)
        entity._is_on = True
        entity._brightness = 200
        entity._refresh_from_cache()
        # State unchanged
        assert entity.is_on is True
        assert entity.brightness == 200


class TestLightHandleModuleChanged:
    def test_matching_module_triggers_refresh_and_write(self, mock_bridge):
        mock_bridge.get_output_level_pct.return_value = 50
        entity = _make_entity(mock_bridge, module="0007")
        entity.async_write_ha_state = MagicMock()

        entity._handle_module_changed(int("0007", 16))

        mock_bridge.get_output_level_pct.assert_called()
        entity.async_write_ha_state.assert_called_once()

    def test_different_module_ignored(self, mock_bridge):
        entity = _make_entity(mock_bridge, module="0007")
        entity.async_write_ha_state = MagicMock()
        mock_bridge.get_output_level_pct.reset_mock()

        entity._handle_module_changed(int("0008", 16))  # different module

        entity.async_write_ha_state.assert_not_called()

    def test_connection_changed_calls_write_ha_state(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        entity.async_write_ha_state = MagicMock()
        entity._handle_connection_changed(True)
        entity.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


class TestLightTurnOn:
    # call signature: set_output_level(module_hex, output, level_pct, transition=...)
    # positional: args[0]=(module_hex, output, level_pct), kwargs: args[1]

    async def test_default_brightness_sends_100pct(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        await entity.async_turn_on()
        mock_bridge.set_output_level.assert_awaited_once()
        args = mock_bridge.set_output_level.call_args
        assert args[0][2] == 100  # ha_to_pct(255) == 100

    async def test_explicit_brightness(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        await entity.async_turn_on(brightness=128)
        args = mock_bridge.set_output_level.call_args
        assert args[0][2] == ha_to_pct(128)

    async def test_explicit_brightness_as_kwarg(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        from homeassistant.components.light import ATTR_BRIGHTNESS
        await entity.async_turn_on(**{ATTR_BRIGHTNESS: 64})
        args = mock_bridge.set_output_level.call_args
        assert args[0][2] == ha_to_pct(64)

    async def test_explicit_transition(self, mock_bridge):
        entity = _make_entity(mock_bridge, default_transition=3)
        from homeassistant.components.light import ATTR_TRANSITION
        await entity.async_turn_on(**{ATTR_TRANSITION: 5})
        args = mock_bridge.set_output_level.call_args
        assert args[1]["transition"] == 5

    async def test_default_transition_used_when_not_specified(self, mock_bridge):
        entity = _make_entity(mock_bridge, default_transition=7)
        await entity.async_turn_on()
        args = mock_bridge.set_output_level.call_args
        assert args[1]["transition"] == 7

    async def test_passes_correct_module_and_output(self, mock_bridge):
        entity = _make_entity(mock_bridge, module="000A", output=3)
        await entity.async_turn_on()
        args = mock_bridge.set_output_level.call_args
        assert args[0][0] == "000A"
        assert args[0][1] == 3


class TestLightTurnOff:
    async def test_sends_level_zero(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        await entity.async_turn_off()
        args = mock_bridge.set_output_level.call_args
        assert args[0][2] == 0  # level_pct is positional arg[2]

    async def test_explicit_transition(self, mock_bridge):
        entity = _make_entity(mock_bridge)
        from homeassistant.components.light import ATTR_TRANSITION
        await entity.async_turn_off(**{ATTR_TRANSITION: 2})
        args = mock_bridge.set_output_level.call_args
        assert args[1]["transition"] == 2

    async def test_default_transition_used(self, mock_bridge):
        entity = _make_entity(mock_bridge, default_transition=4)
        await entity.async_turn_off()
        args = mock_bridge.set_output_level.call_args
        assert args[1]["transition"] == 4


# ---------------------------------------------------------------------------
# Push update end-to-end
# ---------------------------------------------------------------------------


class TestPushUpdateFlow:
    async def test_push_update_updates_entity_state(self, mock_bridge):
        """Simulate a module push: bridge fires listener → entity updates state."""
        # Use a real bridge with controlled get_output_level_pct behavior
        entity = _make_entity(mock_bridge, module="0007", output=0)
        entity.async_write_ha_state = MagicMock()

        # Register the listener (as async_added_to_hass would do)
        await entity.async_added_to_hass()

        # Bridge reports new level
        mock_bridge.get_output_level_pct.return_value = 80

        # Fire the registered listener with the matching module_int
        listener = mock_bridge.add_listener.call_args[0][0]
        listener(int("0007", 16))

        assert entity.is_on is True
        assert entity.brightness == pct_to_ha(80)
        entity.async_write_ha_state.assert_called()
