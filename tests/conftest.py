"""
Shared pytest fixtures and Home Assistant stubs.

HA stubs are installed into sys.modules at import time so every test file
that imports litetouch.* (which in turn imports homeassistant.*) works
without a full HA installation.
"""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Minimal Home-Assistant stubs – installed BEFORE any litetouch.* import
# ---------------------------------------------------------------------------

def _install_ha_stubs() -> None:
    """Populate sys.modules with just enough HA surface for our tests."""
    if "homeassistant" in sys.modules:
        return  # already done

    # --- root package ---
    ha = ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    # --- homeassistant.core ---
    core = ModuleType("homeassistant.core")

    class HomeAssistant:  # noqa: D101
        def __init__(self) -> None:
            self.data: dict = {}
            self.bus = MagicMock()
            self.services = MagicMock()
            self.config_entries = MagicMock()
            self.states = MagicMock()

        async def async_add_executor_job(self, func, *args):
            return func(*args)

        def async_create_task(self, coro):
            return asyncio.ensure_future(coro)

    class ServiceCall:  # noqa: D101
        def __init__(self, domain: str, service: str, data: dict | None = None) -> None:
            self.domain = domain
            self.service = service
            self.data = data or {}

    def callback(func):  # noqa: D103
        return func

    core.HomeAssistant = HomeAssistant
    core.ServiceCall = ServiceCall
    core.callback = callback
    sys.modules["homeassistant.core"] = core

    # --- homeassistant.config_entries ---
    ce = ModuleType("homeassistant.config_entries")

    class ConfigEntry:  # noqa: D101
        def __init__(self) -> None:
            self.entry_id = "test"
            self.data: dict = {}
            self.options: dict = {}

        def async_on_unload(self, cb):
            pass

    ce.SOURCE_IMPORT = "import"
    ce.ConfigEntry = ConfigEntry

    class ConfigFlow:  # noqa: D101
        def __init_subclass__(cls, domain=None, **kwargs):
            super().__init_subclass__(**kwargs)

        def _async_abort_entries_match(self, match):
            pass

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_abort(self, **kwargs):
            return {"type": "abort", **kwargs}

    class OptionsFlowWithReload:  # noqa: D101
        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

    ce.ConfigFlow = ConfigFlow
    ce.OptionsFlowWithReload = OptionsFlowWithReload
    sys.modules["homeassistant.config_entries"] = ce

    # --- homeassistant.components ---
    components = ModuleType("homeassistant.components")
    sys.modules["homeassistant.components"] = components

    # --- homeassistant.components.light ---
    light_mod = ModuleType("homeassistant.components.light")

    class ColorMode:  # noqa: D101
        BRIGHTNESS = "brightness"

    class LightEntityFeature:  # noqa: D101
        TRANSITION = 1

    class LightEntity:  # noqa: D101
        _attr_supported_color_modes: set = set()
        _attr_color_mode: str | None = None

        def async_write_ha_state(self) -> None:  # noqa: D102
            pass

    light_mod.ColorMode = ColorMode
    light_mod.LightEntityFeature = LightEntityFeature
    light_mod.LightEntity = LightEntity
    light_mod.ATTR_BRIGHTNESS = "brightness"
    light_mod.ATTR_TRANSITION = "transition"
    sys.modules["homeassistant.components.light"] = light_mod

    # --- homeassistant.helpers ---
    helpers = ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers

    # homeassistant.helpers.config_validation
    cv = ModuleType("homeassistant.helpers.config_validation")
    cv.string = str
    cv.boolean = bool
    cv.port = int
    cv.ensure_list = lambda x: x if isinstance(x, list) else [x]
    sys.modules["homeassistant.helpers.config_validation"] = cv

    # homeassistant.helpers.selector
    selector_mod = ModuleType("homeassistant.helpers.selector")
    selector_mod.selector = lambda x: x
    sys.modules["homeassistant.helpers.selector"] = selector_mod

    # homeassistant.helpers.typing
    typing_mod = ModuleType("homeassistant.helpers.typing")
    typing_mod.ConfigType = dict
    sys.modules["homeassistant.helpers.typing"] = typing_mod

    # homeassistant.helpers.entity_platform
    ep_mod = ModuleType("homeassistant.helpers.entity_platform")
    ep_mod.AddEntitiesCallback = object  # used only as a type hint
    sys.modules["homeassistant.helpers.entity_platform"] = ep_mod

    # --- homeassistant.util ---
    util = ModuleType("homeassistant.util")
    sys.modules["homeassistant.util"] = util

    # homeassistant.util.dt
    util_dt = ModuleType("homeassistant.util.dt")
    from datetime import datetime, timezone
    util_dt.DEFAULT_TIME_ZONE = timezone.utc
    util_dt.now = lambda tz=None: datetime.now(tz or timezone.utc)
    sys.modules["homeassistant.util.dt"] = util_dt

    # --- homeassistant.exceptions ---
    exc_mod = ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):  # noqa: D101
        pass

    exc_mod.HomeAssistantError = HomeAssistantError
    sys.modules["homeassistant.exceptions"] = exc_mod

    # --- homeassistant.data_entry_flow ---
    flow_mod = ModuleType("homeassistant.data_entry_flow")
    flow_mod.FlowResult = dict
    sys.modules["homeassistant.data_entry_flow"] = flow_mod


# Install stubs immediately at conftest import time
_install_ha_stubs()

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hass():
    """Minimal HomeAssistant-like object."""
    hass = MagicMock()
    hass.data = {}
    hass.bus.async_listen_once = MagicMock()
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.states.async_set = MagicMock()

    hass.async_create_task = MagicMock(return_value=None)
    return hass


@pytest.fixture
def mock_config_entry():
    """Config entry with sensible defaults."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        "host": "10.0.0.1",
        "port": 10001,
        "command_connections": 2,
        "event_connection": True,
        "transition": 2,
    }
    entry.options = {
        "lights": [
            {"name": "Kitchen", "module": "0007", "output": 0},
        ]
    }
    entry.async_on_unload = MagicMock()
    return entry


@pytest.fixture
def mock_client():
    """Fully mocked LiteTouchClient."""
    client = AsyncMock()
    client.on_module_update = None
    client.on_connection_change = None
    client.get_module_levels = AsyncMock(return_value=("FF", [50, 0, 0, 0, 0, 0, 0, 0]))
    client.set_module_levels = AsyncMock()
    client.set_module_notify = AsyncMock()
    client.toggle_switch = AsyncMock()
    client.set_loads_on = AsyncMock()
    client.set_loads_off = AsyncMock()
    client.initialize_load_levels = AsyncMock()
    client.press_switch = AsyncMock()
    client.hold_switch = AsyncMock()
    client.release_switch = AsyncMock()
    client.press_hold_switch = AsyncMock()
    client.set_led_on = AsyncMock()
    client.set_led_off = AsyncMock()
    client.set_load_levels = AsyncMock()
    client.set_previous_load_states = AsyncMock()
    client.open_loads = AsyncMock()
    client.close_loads = AsyncMock()
    client.stop_loads = AsyncMock()
    client.start_ramp = AsyncMock()
    client.stop_ramp = AsyncMock()
    client.start_ramp_to_min = AsyncMock()
    client.start_ramp_to_max = AsyncMock()
    client.lock_loads = AsyncMock()
    client.unlock_loads = AsyncMock()
    client.lock_switch = AsyncMock()
    client.unlock_switch = AsyncMock()
    client.lock_timer = AsyncMock()
    client.unlock_timer = AsyncMock()
    client.increment_load_levels = AsyncMock()
    client.decrement_load_levels = AsyncMock()
    client.set_global = AsyncMock()
    client.copy_current_to_preset_levels = AsyncMock()
    client.set_clock = AsyncMock()
    return client


@pytest.fixture
def real_bridge(mock_client):
    """Real LiteTouchBridge with a mocked LiteTouchClient injected."""
    from litetouch.litetouch_bridge import LiteTouchBridge

    bridge = LiteTouchBridge.__new__(LiteTouchBridge)
    bridge._client = mock_client
    bridge._default_transition = 3
    bridge._module_levels = {}
    bridge._listeners = []
    bridge._connection_listeners = []
    bridge._locks = {}
    bridge._connected = False

    # Wire the callbacks as __init__ would
    mock_client.on_module_update = bridge._on_module_update
    mock_client.on_connection_change = bridge._on_connection_change

    return bridge


@pytest.fixture
def mock_bridge():
    """Fully mocked LiteTouchBridge for entity/service tests."""
    bridge = MagicMock()
    bridge.connected = True
    bridge.start = AsyncMock()
    bridge.stop = AsyncMock()
    bridge.get_output_level_pct = MagicMock(return_value=50)
    bridge.set_output_level = AsyncMock()
    bridge.set_module_levels = AsyncMock()
    bridge.ensure_module_notify = AsyncMock()
    bridge.ensure_module_cached = AsyncMock()
    bridge.lt_toggle_switch = AsyncMock()
    bridge.set_load_on = AsyncMock()
    bridge.set_load_off = AsyncMock()
    bridge.initialize_load_levels = AsyncMock()
    bridge.press_switch = AsyncMock()
    bridge.hold_switch = AsyncMock()
    bridge.release_switch = AsyncMock()
    bridge.press_hold_switch = AsyncMock()
    bridge.set_led_on = AsyncMock()
    bridge.set_led_off = AsyncMock()
    bridge.recall_load_preset = AsyncMock()
    bridge.restore_load_states = AsyncMock()
    bridge.save_load_preset = AsyncMock()
    bridge.open_loads = AsyncMock()
    bridge.close_loads = AsyncMock()
    bridge.stop_loads = AsyncMock()
    bridge.start_ramp = AsyncMock()
    bridge.stop_ramp = AsyncMock()
    bridge.start_ramp_to_min = AsyncMock()
    bridge.start_ramp_to_max = AsyncMock()
    bridge.lock_loads = AsyncMock()
    bridge.unlock_loads = AsyncMock()
    bridge.lock_switch = AsyncMock()
    bridge.unlock_switch = AsyncMock()
    bridge.lock_timer = AsyncMock()
    bridge.unlock_timer = AsyncMock()
    bridge.increment_load_levels = AsyncMock()
    bridge.decrement_load_levels = AsyncMock()
    bridge.set_global = AsyncMock()
    bridge.set_clock = AsyncMock()

    _listeners: list = []
    _conn_listeners: list = []

    def add_listener(cb):
        _listeners.append(cb)
        def _remove():
            if cb in _listeners:
                _listeners.remove(cb)
        return _remove

    def add_connection_listener(cb):
        _conn_listeners.append(cb)
        def _remove():
            if cb in _conn_listeners:
                _conn_listeners.remove(cb)
        return _remove

    bridge.add_listener = MagicMock(side_effect=add_listener)
    bridge.add_connection_listener = MagicMock(side_effect=add_connection_listener)
    bridge._listeners = _listeners
    bridge._conn_listeners = _conn_listeners
    return bridge


@pytest.fixture
def mock_tcp():
    """Patch asyncio.open_connection to return a fake reader/writer pair."""
    from unittest.mock import patch

    reader = AsyncMock(spec=asyncio.StreamReader)
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.is_closing = MagicMock(return_value=False)
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()

    with patch("asyncio.open_connection", return_value=(reader, writer)) as patched:
        yield patched, reader, writer
