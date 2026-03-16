import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import EntityPlatform

from .const import (
    CONF_COMMAND_CONNECTIONS,
    CONF_EVENT_CONNECTION,
    CONF_TRANSITION,
    CONF_LIGHTS,
    CONF_HOST,
    CONF_PORT,
)
from .litetouch_bridge import LiteTouchBridge
from .light import LiteTouchLightEntity
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up LiteTouch from YAML."""
    lt_config = config.get("litetouch")
    if not lt_config:
        return True

    host = lt_config[CONF_HOST]
    port = lt_config[CONF_PORT]
    command_connections = lt_config.get(CONF_COMMAND_CONNECTIONS, 4)
    event_connection = lt_config.get(CONF_EVENT_CONNECTION, True)
    transition = lt_config.get(CONF_TRANSITION, 1)

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

    hass.bus.async_listen_once("homeassistant_stop", _shutdown)

    entities = []
    for item in lt_config[CONF_LIGHTS]:
        entities.append(LiteTouchLightEntity(bridge, item, transition))

    # Create a platform to add the entities
    platform = EntityPlatform(
        hass=hass,
        logger=_LOGGER,
        domain="light",
        platform_name="litetouch",
        platform=None,
        scan_interval=timedelta.max,
        entity_namespace=None,
    )
    await platform.async_add_entities(entities)

    async_setup_services(hass, bridge)

    return True