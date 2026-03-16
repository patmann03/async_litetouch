"""LiteTouch integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_COMMAND_CONNECTIONS,
    CONF_EVENT_CONNECTION,
    CONF_TRANSITION,
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
)
from .litetouch_bridge import LiteTouchBridge
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LiteTouch from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    command_connections = entry.data.get(CONF_COMMAND_CONNECTIONS, 4)
    event_connection = entry.data.get(CONF_EVENT_CONNECTION, True)
    transition = entry.data.get(CONF_TRANSITION, 1)

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

    # Reload integration when options change
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    # Set up services
    async_setup_services(hass, bridge)

    # Forward the setup to the light platform
    await hass.config_entries.async_forward_entry_setups(entry, ["light"])

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    bridge = data["bridge"]
    await bridge.stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["light"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


# Keep YAML setup for backward compatibility, but mark as deprecated
async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up LiteTouch from YAML (deprecated)."""
    _LOGGER.warning(
        "YAML configuration for LiteTouch is deprecated. Please use the UI."
    )
    # You could implement YAML setup here if needed, but since we're moving to UI, perhaps not.
    return True
