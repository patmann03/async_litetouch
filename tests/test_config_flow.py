"""Tests for litetouch/config_flow.py — ConfigFlow and OptionsFlow."""

from __future__ import annotations

import pytest
import voluptuous as vol

from litetouch.config_flow import ConfigFlow, OptionsFlow, _validate_lights


# ---------------------------------------------------------------------------
# _validate_lights
# ---------------------------------------------------------------------------


class TestValidateLights:
    def test_accepts_loadid_only(self):
        lights = [{"name": "Kitchen", "loadid": 1}]
        result = _validate_lights(lights)
        assert result[0]["loadid"] == 1

    def test_accepts_module_and_output(self):
        lights = [{"name": "Dining", "module": "0007", "output": 0}]
        result = _validate_lights(lights)
        assert result is not None

    def test_rejects_missing_both(self):
        lights = [{"name": "Hallway"}]
        with pytest.raises(vol.Invalid):
            _validate_lights(lights)

    def test_rejects_module_without_output(self):
        lights = [{"name": "Kitchen", "module": "0007"}]
        with pytest.raises(vol.Invalid):
            _validate_lights(lights)

    def test_rejects_output_without_module(self):
        lights = [{"name": "Kitchen", "output": 0}]
        with pytest.raises(vol.Invalid):
            _validate_lights(lights)

    def test_coerces_loadid_string_to_int(self):
        lights = [{"name": "Kitchen", "loadid": "3"}]
        result = _validate_lights(lights)
        assert result[0]["loadid"] == 3
        assert isinstance(result[0]["loadid"], int)

    def test_coerces_output_string_to_int(self):
        lights = [{"name": "Kitchen", "module": "0007", "output": "2"}]
        result = _validate_lights(lights)
        assert result[0]["output"] == 2
        assert isinstance(result[0]["output"], int)

    def test_invalid_loadid_string_raises(self):
        lights = [{"name": "Kitchen", "loadid": "not_a_number"}]
        with pytest.raises(vol.Invalid):
            _validate_lights(lights)

    def test_empty_list_is_valid(self):
        result = _validate_lights([])
        assert result == []

    def test_multiple_lights_all_validated(self):
        lights = [
            {"name": "A", "loadid": 1},
            {"name": "B", "module": "0007", "output": 0},
        ]
        result = _validate_lights(lights)
        assert len(result) == 2

    def test_one_invalid_light_raises(self):
        lights = [
            {"name": "A", "loadid": 1},
            {"name": "B"},  # missing loadid and module/output
        ]
        with pytest.raises(vol.Invalid):
            _validate_lights(lights)


# ---------------------------------------------------------------------------
# ConfigFlow.async_step_user
# ---------------------------------------------------------------------------


class TestConfigFlowStepUser:
    def _make_flow(self):
        flow = ConfigFlow()
        flow.hass = None  # validate_input is a stub
        return flow

    async def test_returns_form_on_no_input(self):
        flow = self._make_flow()
        result = await flow.async_step_user(None)
        assert result["type"] == "form"

    async def test_creates_entry_on_valid_input(self):
        flow = self._make_flow()
        user_input = {
            "host": "10.0.0.1",
            "port": 10001,
            "command_connections": 2,
            "event_connection": True,
            "transition": 2,
        }
        result = await flow.async_step_user(user_input)
        assert result["type"] == "create_entry"
        assert result["data"]["host"] == "10.0.0.1"

    async def test_entry_title_is_litetouch(self):
        flow = self._make_flow()
        user_input = {"host": "10.0.0.1", "port": 10001}
        result = await flow.async_step_user(user_input)
        assert result["title"] == "LiteTouch"


# ---------------------------------------------------------------------------
# ConfigFlow.async_step_import
# ---------------------------------------------------------------------------


class TestConfigFlowStepImport:
    def _make_flow(self):
        flow = ConfigFlow()
        flow.hass = None
        # _async_abort_entries_match is a no-op in our stub
        return flow

    async def test_creates_entry_from_import(self):
        flow = self._make_flow()
        import_config = {
            "host": "10.0.0.2",
            "port": 10001,
            "lights": [{"name": "K", "loadid": 1}],
        }
        result = await flow.async_step_import(import_config)
        assert result["type"] == "create_entry"

    async def test_lights_moved_to_options(self):
        flow = self._make_flow()
        import_config = {
            "host": "10.0.0.2",
            "port": 10001,
            "lights": [{"name": "K", "loadid": 1}],
        }
        result = await flow.async_step_import(import_config)
        # data should NOT contain lights (it goes to options)
        assert "lights" not in result.get("data", {})
        assert result["options"]["lights"] == [{"name": "K", "loadid": 1}]

    async def test_data_contains_host_and_port(self):
        flow = self._make_flow()
        import_config = {"host": "10.0.0.2", "port": 10001}
        result = await flow.async_step_import(import_config)
        assert result["data"]["host"] == "10.0.0.2"
        assert result["data"]["port"] == 10001


# ---------------------------------------------------------------------------
# OptionsFlow.async_step_init
# ---------------------------------------------------------------------------


class TestOptionsFlowStepInit:
    def _make_flow(self, existing_lights=None):
        flow = OptionsFlow()
        entry = type("Entry", (), {"options": {"lights": existing_lights or []}})()
        flow.config_entry = entry
        return flow

    async def test_returns_form_on_no_input(self):
        flow = self._make_flow()
        result = await flow.async_step_init(None)
        assert result["type"] == "form"

    async def test_saves_lights_on_valid_input(self):
        flow = self._make_flow()
        lights = [{"name": "K", "loadid": 1}]
        result = await flow.async_step_init({"lights": lights})
        assert result["type"] == "create_entry"
        assert result["data"]["lights"] == lights

    async def test_returns_form_with_error_on_invalid_lights(self):
        flow = self._make_flow()
        # No loadid, no module/output → invalid
        lights = [{"name": "Bad"}]
        result = await flow.async_step_init({"lights": lights})
        assert result["type"] == "form"
        assert "lights" in result.get("errors", {})

    async def test_empty_lights_list_is_valid(self):
        flow = self._make_flow()
        result = await flow.async_step_init({"lights": []})
        assert result["type"] == "create_entry"
