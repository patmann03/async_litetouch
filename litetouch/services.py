"""Services for the LiteTouch integration."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable

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

# Service names (must be lowercase / underscore)
SERVICE_SET_CLOCK = "set_clock"
SERVICE_SET_MODULE_LEVELS = "set_module_levels"
SERVICE_TOGGLE_SWITCH = "toggle_switch"

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


async def _async_call_client(
    hass: HomeAssistant,
    func: Callable[..., Any],
    *args: Any,
) -> Any:
    """Call a client function safely, handling both sync and async implementations.

    - If func is async (coroutine function), await it directly.
    - If func is sync, run it in the executor.
    - If a sync call returns a coroutine object, await it on the event loop.
    """
    if inspect.iscoroutinefunction(func):
        # Async client method: must be awaited directly (not in executor)
        return await func(*args)

    # Sync client method: run in executor to avoid blocking the event loop
    result = await hass.async_add_executor_job(func, *args)

    # Some libraries dynamically return coroutine objects even from sync wrappers.
    # If so, await the coroutine here on the event loop.
    if asyncio.iscoroutine(result):
        return await result

    return result


@callback
def async_setup_services(hass: HomeAssistant, bridge) -> None:
    """Set up the services for the LiteTouch integration."""

    async def handle_set_clock(call: ServiceCall) -> None:
        """Set controller clock to current HA local time."""
        now = dt.now(dt.DEFAULT_TIME_ZONE)
        clock = now.strftime("%Y%m%d%H%M%S")

        await _async_call_client(hass, bridge._client.set_clock, clock)

        # Optional: expose last-set time in state machine for debugging
        hass.states.set(f"{DOMAIN}.last_clock_set", now.isoformat())

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CLOCK,
        handle_set_clock,
        # no schema needed; takes no parameters
    )

    async def handle_set_module_levels(call: ServiceCall) -> None:
        """Set module output levels."""
        module_hex = call.data[MODULE]
        bitmap_hex = call.data[BITMAP]
        time_seconds = call.data[RAMP]
        levels = call.data[LEVELS]

        await _async_call_client(
            hass,
            bridge._client.set_module_levels,
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
