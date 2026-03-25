"""Services for the LiteTouch integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt

_LOGGER = logging.getLogger(__name__)

DOMAIN = "litetouch"

# Field keys
MODULE = "module"
BITMAP = "bitmap"
RAMP = "ramp"
LEVELS = "levels"
CONF_SWITCH = "switch"
LOADID = "loadid"
LVL = "brightness_level"
CONF_TIMER = "timer_id"
CONF_ADDRESS = "address"
CONF_VALUE = "value"
CONF_STEP = "step"

# Service names (must be lowercase / underscore)
SERVICE_SET_CLOCK = "set_clock"
SERVICE_SET_MODULE_LEVELS = "set_module_levels"
SERVICE_TOGGLE_SWITCH = "toggle_switch"
SERVICE_LOAD_ON = "set_load_on"
SERVICE_LOAD_OFF = "set_load_off"
SERVICE_LOAD_LVL = "set_load_level"
SERVICE_PRESS_SWITCH = "press_switch"
SERVICE_HOLD_SWITCH = "hold_switch"
SERVICE_RELEASE_SWITCH = "release_switch"
SERVICE_PRESS_HOLD_SWITCH = "press_hold_switch"
SERVICE_SET_LED_ON = "set_led_on"
SERVICE_SET_LED_OFF = "set_led_off"
SERVICE_RECALL_PRESET = "recall_load_preset"
SERVICE_RESTORE_STATES = "restore_load_states"
SERVICE_OPEN_LOADS = "open_loads"
SERVICE_CLOSE_LOADS = "close_loads"
SERVICE_STOP_LOADS = "stop_loads"
SERVICE_START_RAMP = "start_ramp"
SERVICE_STOP_RAMP = "stop_ramp"
SERVICE_RAMP_TO_MIN = "ramp_to_min"
SERVICE_RAMP_TO_MAX = "ramp_to_max"
SERVICE_LOCK_LOADS = "lock_loads"
SERVICE_UNLOCK_LOADS = "unlock_loads"
SERVICE_LOCK_SWITCH = "lock_switch"
SERVICE_UNLOCK_SWITCH = "unlock_switch"
SERVICE_LOCK_TIMER = "lock_timer"
SERVICE_UNLOCK_TIMER = "unlock_timer"
SERVICE_INCREMENT_LEVELS = "increment_load_levels"
SERVICE_DECREMENT_LEVELS = "decrement_load_levels"
SERVICE_SET_GLOBAL = "set_global"
SERVICE_SAVE_PRESET = "save_load_preset"

# Schemas
TOGGLE_SWITCH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SWITCH): cv.string,
    }
)

MODULE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(MODULE): cv.string,
        vol.Required(BITMAP): cv.string,
        vol.Required(RAMP): vol.Coerce(int),
        vol.Required(LEVELS): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)

LOADID_SCHEMA = vol.Schema(
    {
        vol.Required(LOADID): vol.Coerce(int),
        vol.Optional(LVL): vol.Coerce(int),
    }
)

LOAD_GROUP_SCHEMA = vol.Schema(
    {
        vol.Required(LOADID): vol.Coerce(int),
    }
)

LOAD_STEP_SCHEMA = vol.Schema(
    {
        vol.Required(LOADID): vol.Coerce(int),
        vol.Required(CONF_STEP): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)

TIMER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TIMER): vol.Coerce(int),
    }
)

GLOBAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADDRESS): vol.Coerce(int),
        vol.Required(CONF_VALUE): vol.Coerce(int),
    }
)

ALL_SERVICES = [
    SERVICE_SET_CLOCK, SERVICE_SET_MODULE_LEVELS, SERVICE_TOGGLE_SWITCH,
    SERVICE_LOAD_OFF, SERVICE_LOAD_ON, SERVICE_LOAD_LVL,
    SERVICE_PRESS_SWITCH, SERVICE_HOLD_SWITCH, SERVICE_RELEASE_SWITCH,
    SERVICE_PRESS_HOLD_SWITCH, SERVICE_SET_LED_ON, SERVICE_SET_LED_OFF,
    SERVICE_RECALL_PRESET, SERVICE_RESTORE_STATES, SERVICE_SAVE_PRESET,
    SERVICE_OPEN_LOADS, SERVICE_CLOSE_LOADS, SERVICE_STOP_LOADS,
    SERVICE_START_RAMP, SERVICE_STOP_RAMP, SERVICE_RAMP_TO_MIN,
    SERVICE_RAMP_TO_MAX, SERVICE_LOCK_LOADS, SERVICE_UNLOCK_LOADS,
    SERVICE_LOCK_SWITCH, SERVICE_UNLOCK_SWITCH, SERVICE_LOCK_TIMER,
    SERVICE_UNLOCK_TIMER, SERVICE_INCREMENT_LEVELS, SERVICE_DECREMENT_LEVELS,
    SERVICE_SET_GLOBAL,
]


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove all registered LiteTouch services."""
    for svc in ALL_SERVICES:
        hass.services.async_remove(DOMAIN, svc)


@callback
def async_setup_services(hass: HomeAssistant, bridge) -> None:
    """Set up the services for the LiteTouch integration."""

    async def handle_set_clock(call: ServiceCall) -> None:
        """Set controller clock to current HA local time."""
        now = dt.now(dt.DEFAULT_TIME_ZONE)
        clock = now.strftime("%Y%m%d%H%M%S")

        await bridge.set_clock(clock)

        # Optional: expose last-set time in state machine for debugging
        hass.states.async_set(f"{DOMAIN}.last_clock_set", now.isoformat())

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CLOCK,
        handle_set_clock,
        # no schema needed; takes no parameters
    )

    async def handle_set_module_levels(call: ServiceCall) -> None:
        """Set module output levels via raw DSMLV."""
        module_hex = call.data[MODULE]
        bitmap_hex = call.data[BITMAP]
        time_seconds = call.data[RAMP]
        levels = call.data[LEVELS]

        await bridge.set_module_levels(
            module_hex,
            bitmap_hex,
            time_seconds,
            levels,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MODULE_LEVELS,
        handle_set_module_levels,
        schema=MODULE_SERVICE_SCHEMA,
    )

    async def handle_toggle_switch(call: ServiceCall) -> None:
        """Toggle a switch (button press equivalent)."""
        switch = call.data[CONF_SWITCH]
        _LOGGER.debug("LiteTouch service called: %s", call.service)
        await bridge.lt_toggle_switch(switch)
        # await _async_call_client(hass, bridge.lt_toggle_switch, switch)
        return True

    hass.services.async_register(
        DOMAIN,
        SERVICE_TOGGLE_SWITCH,
        handle_toggle_switch,
        schema=TOGGLE_SWITCH_SCHEMA,
    )


    async def turn_load_off(call: ServiceCall) -> None:
        """Turn Load Off"""
        loadid = call.data[LOADID]
        _LOGGER.debug("LiteTouch service called: %s", call.service)
        await bridge.set_load_off(loadid)
        # await _async_call_client(hass, bridge.lt_toggle_switch, switch)
        return True

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOAD_OFF,
        turn_load_off,
        schema=LOADID_SCHEMA,
    )

    async def turn_load_on(call: ServiceCall) -> None:
        """Turn Load On"""
        loadid = call.data[LOADID]
        _LOGGER.debug("LiteTouch service called: %s", call.service)
        await bridge.set_load_on(loadid)
        # await _async_call_client(hass, bridge.lt_toggle_switch, switch)
        return True

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOAD_ON,
        turn_load_on,
        schema=LOADID_SCHEMA,
    )

    async def set_load_level(call: ServiceCall) -> None:
        """Set Load Level (Brightness)."""
        loadid = call.data[LOADID]
        lvl = call.data[LVL]
        _LOGGER.debug("LiteTouch service called: %s", call.service)
        await bridge.initialize_load_levels(loadid, lvl)
        return True

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOAD_LVL,
        set_load_level,
        schema=LOADID_SCHEMA,
    )

    # ---- Switch press/hold/release services ----

    async def handle_press_switch(call: ServiceCall) -> None:
        """Press a keypad button."""
        await bridge.press_switch(call.data[CONF_SWITCH])

    hass.services.async_register(
        DOMAIN, SERVICE_PRESS_SWITCH, handle_press_switch, schema=TOGGLE_SWITCH_SCHEMA
    )

    async def handle_hold_switch(call: ServiceCall) -> None:
        """Hold a keypad button."""
        await bridge.hold_switch(call.data[CONF_SWITCH])

    hass.services.async_register(
        DOMAIN, SERVICE_HOLD_SWITCH, handle_hold_switch, schema=TOGGLE_SWITCH_SCHEMA
    )

    async def handle_release_switch(call: ServiceCall) -> None:
        """Release a held keypad button."""
        await bridge.release_switch(call.data[CONF_SWITCH])

    hass.services.async_register(
        DOMAIN, SERVICE_RELEASE_SWITCH, handle_release_switch, schema=TOGGLE_SWITCH_SCHEMA
    )

    async def handle_press_hold_switch(call: ServiceCall) -> None:
        """Press and hold a keypad button."""
        await bridge.press_hold_switch(call.data[CONF_SWITCH])

    hass.services.async_register(
        DOMAIN, SERVICE_PRESS_HOLD_SWITCH, handle_press_hold_switch, schema=TOGGLE_SWITCH_SCHEMA
    )

    # ---- LED services ----

    async def handle_set_led_on(call: ServiceCall) -> None:
        """Turn on a keypad LED."""
        await bridge.set_led_on(call.data[CONF_SWITCH])

    hass.services.async_register(
        DOMAIN, SERVICE_SET_LED_ON, handle_set_led_on, schema=TOGGLE_SWITCH_SCHEMA
    )

    async def handle_set_led_off(call: ServiceCall) -> None:
        """Turn off a keypad LED."""
        await bridge.set_led_off(call.data[CONF_SWITCH])

    hass.services.async_register(
        DOMAIN, SERVICE_SET_LED_OFF, handle_set_led_off, schema=TOGGLE_SWITCH_SCHEMA
    )

    # ---- Load group preset/state services ----

    async def handle_recall_preset(call: ServiceCall) -> None:
        """Recall saved preset levels for a load group."""
        await bridge.recall_load_preset(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_RECALL_PRESET, handle_recall_preset, schema=LOAD_GROUP_SCHEMA
    )

    async def handle_restore_states(call: ServiceCall) -> None:
        """Restore previous load states for a load group."""
        await bridge.restore_load_states(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_RESTORE_STATES, handle_restore_states, schema=LOAD_GROUP_SCHEMA
    )

    async def handle_save_preset(call: ServiceCall) -> None:
        """Copy current levels to preset for a load group."""
        await bridge.save_load_preset(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_SAVE_PRESET, handle_save_preset, schema=LOAD_GROUP_SCHEMA
    )

    # ---- Relay load open/close/stop services ----

    async def handle_open_loads(call: ServiceCall) -> None:
        """Open relay loads in a load group."""
        await bridge.open_loads(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_OPEN_LOADS, handle_open_loads, schema=LOAD_GROUP_SCHEMA
    )

    async def handle_close_loads(call: ServiceCall) -> None:
        """Close relay loads in a load group."""
        await bridge.close_loads(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_CLOSE_LOADS, handle_close_loads, schema=LOAD_GROUP_SCHEMA
    )

    async def handle_stop_loads(call: ServiceCall) -> None:
        """Stop loads in a load group."""
        await bridge.stop_loads(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_STOP_LOADS, handle_stop_loads, schema=LOAD_GROUP_SCHEMA
    )

    # ---- Ramp services ----

    async def handle_start_ramp(call: ServiceCall) -> None:
        """Start ramping a load group."""
        await bridge.start_ramp(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_START_RAMP, handle_start_ramp, schema=LOAD_GROUP_SCHEMA
    )

    async def handle_stop_ramp(call: ServiceCall) -> None:
        """Stop ramping a load group."""
        await bridge.stop_ramp(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_STOP_RAMP, handle_stop_ramp, schema=LOAD_GROUP_SCHEMA
    )

    async def handle_ramp_to_min(call: ServiceCall) -> None:
        """Ramp a load group to its minimum level."""
        await bridge.start_ramp_to_min(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_RAMP_TO_MIN, handle_ramp_to_min, schema=LOAD_GROUP_SCHEMA
    )

    async def handle_ramp_to_max(call: ServiceCall) -> None:
        """Ramp a load group to its maximum level."""
        await bridge.start_ramp_to_max(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_RAMP_TO_MAX, handle_ramp_to_max, schema=LOAD_GROUP_SCHEMA
    )

    # ---- Lock/unlock services ----

    async def handle_lock_loads(call: ServiceCall) -> None:
        """Lock a load group."""
        await bridge.lock_loads(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_LOCK_LOADS, handle_lock_loads, schema=LOAD_GROUP_SCHEMA
    )

    async def handle_unlock_loads(call: ServiceCall) -> None:
        """Unlock a load group."""
        await bridge.unlock_loads(call.data[LOADID])

    hass.services.async_register(
        DOMAIN, SERVICE_UNLOCK_LOADS, handle_unlock_loads, schema=LOAD_GROUP_SCHEMA
    )

    async def handle_lock_switch(call: ServiceCall) -> None:
        """Lock a keypad switch."""
        await bridge.lock_switch(call.data[CONF_SWITCH])

    hass.services.async_register(
        DOMAIN, SERVICE_LOCK_SWITCH, handle_lock_switch, schema=TOGGLE_SWITCH_SCHEMA
    )

    async def handle_unlock_switch(call: ServiceCall) -> None:
        """Unlock a keypad switch."""
        await bridge.unlock_switch(call.data[CONF_SWITCH])

    hass.services.async_register(
        DOMAIN, SERVICE_UNLOCK_SWITCH, handle_unlock_switch, schema=TOGGLE_SWITCH_SCHEMA
    )

    async def handle_lock_timer(call: ServiceCall) -> None:
        """Lock a timer."""
        await bridge.lock_timer(call.data[CONF_TIMER])

    hass.services.async_register(
        DOMAIN, SERVICE_LOCK_TIMER, handle_lock_timer, schema=TIMER_SCHEMA
    )

    async def handle_unlock_timer(call: ServiceCall) -> None:
        """Unlock a timer."""
        await bridge.unlock_timer(call.data[CONF_TIMER])

    hass.services.async_register(
        DOMAIN, SERVICE_UNLOCK_TIMER, handle_unlock_timer, schema=TIMER_SCHEMA
    )

    # ---- Level adjustment services ----

    async def handle_increment_levels(call: ServiceCall) -> None:
        """Increment load group brightness by a step amount."""
        await bridge.increment_load_levels(call.data[LOADID], call.data[CONF_STEP])

    hass.services.async_register(
        DOMAIN, SERVICE_INCREMENT_LEVELS, handle_increment_levels, schema=LOAD_STEP_SCHEMA
    )

    async def handle_decrement_levels(call: ServiceCall) -> None:
        """Decrement load group brightness by a step amount."""
        await bridge.decrement_load_levels(call.data[LOADID], call.data[CONF_STEP])

    hass.services.async_register(
        DOMAIN, SERVICE_DECREMENT_LEVELS, handle_decrement_levels, schema=LOAD_STEP_SCHEMA
    )

    # ---- Global variable service ----

    async def handle_set_global(call: ServiceCall) -> None:
        """Set a controller global variable."""
        await bridge.set_global(call.data[CONF_ADDRESS], call.data[CONF_VALUE])

    hass.services.async_register(
        DOMAIN, SERVICE_SET_GLOBAL, handle_set_global, schema=GLOBAL_SCHEMA
    )