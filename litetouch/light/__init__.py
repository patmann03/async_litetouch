"""Light platform for LiteTouch integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import CONF_LIGHTS, DOMAIN
from .light import LiteTouchLightEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the LiteTouch light platform."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    bridge = data["bridge"]
    options = config_entry.options
    lights = options.get(CONF_LIGHTS, [])

    entities = []
    for item in lights:
        entities.append(LiteTouchLightEntity(bridge, item, bridge._default_transition))

    async_add_entities(entities)