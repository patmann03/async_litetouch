"""LiteTouch integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BUTTON,
    CONF_COMMAND_CONNECTIONS,
    CONF_EVENT_CONNECTION,
    CONF_FLOOR,
    CONF_HOST,
    CONF_LIGHTS,
    CONF_LOADID,
    CONF_LOCATION,
    CONF_LTCODE,
    CONF_MODULE,
    CONF_NAME,
    CONF_OUTPUT,
    CONF_PORT,
    CONF_STATION,
    CONF_TRANSITION,
    DOMAIN,
)
from .litetouch_bridge import LiteTouchBridge
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

LIGHT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_MODULE): cv.string,
        vol.Optional(CONF_OUTPUT): int,
        vol.Optional(CONF_LOADID): int,
        vol.Optional(CONF_STATION): cv.string,
        vol.Optional(CONF_BUTTON): cv.string,
        vol.Optional(CONF_LOCATION): cv.string,
        vol.Optional(CONF_FLOOR): cv.string,
        vol.Optional(CONF_LTCODE): cv.string,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=10001): cv.port,
                vol.Optional(CONF_COMMAND_CONNECTIONS, default=4): vol.All(
                    int, vol.Range(min=1)
                ),
                vol.Optional(CONF_EVENT_CONNECTION, default=True): cv.boolean,
                vol.Optional(CONF_TRANSITION, default=2): vol.All(
                    int, vol.Range(min=0)
                ),
                vol.Optional(CONF_LIGHTS, default=[]): vol.All(
                    cv.ensure_list, [LIGHT_SCHEMA]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up LiteTouch from YAML configuration if present."""
    if DOMAIN not in config:
        return True

    _LOGGER.debug("LiteTouch YAML config found, importing via config entry")
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=dict(config[DOMAIN]),
        )
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LiteTouch from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    command_connections = entry.data.get(CONF_COMMAND_CONNECTIONS, 4)
    event_connection = entry.data.get(CONF_EVENT_CONNECTION, True)
    transition = entry.data.get(CONF_TRANSITION, 2)

    bridge = LiteTouchBridge(
        host,
        port,
        command_connections=command_connections,
        event_connection=event_connection,
        default_transition=transition,
    )

    await bridge.start()

    # Ensure we close cleanly on shutdown
    async def _shutdown(_event):
        await bridge.stop()

    entry.async_on_unload(hass.bus.async_listen_once("homeassistant_stop", _shutdown))

    # Store the bridge
    hass.data[DOMAIN][entry.entry_id] = {"bridge": bridge, "config": entry}

    # Set up services
    async_setup_services(hass, bridge)

    # Forward the setup to the light platform
    await hass.config_entries.async_forward_entry_setups(entry, ["light"])

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    bridge = data["bridge"]
    await bridge.stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["light"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
