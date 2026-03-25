from __future__ import annotations

import logging

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)

from ..const import (
    CONF_COMMAND_CONNECTIONS,
    CONF_EVENT_CONNECTION,
    CONF_TRANSITION,
    CONF_LIGHTS,
    CONF_NAME,
    CONF_STATION,
    CONF_BUTTON,
    CONF_LOADID,
    CONF_MODULE,
    CONF_OUTPUT,
    CONF_LOCATION,
    CONF_FLOOR,
    CONF_LTCODE,
)
from ..litetouch_bridge import LiteTouchBridge, pct_to_ha, ha_to_pct

_LOGGER = logging.getLogger(__name__)


class LiteTouchLightEntity(LightEntity):
    """One HA Light mapped to one LiteTouch module+output."""

    _attr_supported_color_modes = {
        ColorMode.BRIGHTNESS
    }  # required for new integrations [4](https://developers.home-assistant.io/docs/core/entity/light/)
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self, bridge: LiteTouchBridge, cfg: dict, default_transition: int
    ) -> None:
        self._bridge = bridge
        self._name = cfg[CONF_NAME]
        self._module_hex = cfg[CONF_MODULE]
        self._module_int = int(self._module_hex, 16)
        self._output = int(cfg[CONF_OUTPUT])
        self._default_transition = default_transition

        # metadata requested in config
        self._station = cfg.get(CONF_STATION)
        self._button = cfg.get(CONF_BUTTON)
        self._loadid_config = cfg.get(CONF_LOADID)
        if self._loadid_config is not None:
            self._loadid = self._loadid_config - 1  # Adjust load ID down 1 as 0 based
        else:
            self._loadid = cfg.get(CONF_LOADID)
        self._location = cfg.get(CONF_LOCATION)
        self._floor = cfg.get(CONF_FLOOR)
        self._ltcode = cfg.get(CONF_LTCODE)

        self._remove_listener = None
        self._remove_connection_listener = None

        self._is_on = False
        self._brightness = 0  # HA 0..255

    @property
    def unique_id(self):
        return f"litetouch_rtc.{self._module_hex}_{self._output}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def extra_state_attributes(self):
        # expose config metadata (useful for debugging/automation)
        return {
            "module": self._module_hex,
            "output": self._output,
            "loadid_Config": self._loadid_config,
            "loadid": self._loadid,
            "station": self._station,
            "button": self._button,
            "floor": self._floor,
            "location": self._location,
            "ltcode": self._ltcode,
        }

    @property
    def available(self) -> bool:
        return self._bridge.connected

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int | None:
        return self._brightness

    @property
    def supported_features(self) -> LightEntityFeature:
        """Flag supported features."""

        return LightEntityFeature.TRANSITION

    @property
    def should_poll(self) -> bool:
        # We are push-driven (RMODU). [1](https://developers.home-assistant.io/docs/creating_integration_manifest/)
        return False

    async def async_added_to_hass(self) -> None:
        # enable module notifications for this module
        await self._bridge.ensure_module_notify(self._module_hex)

        # seed cache (optional but helps initial state)
        await self._bridge.ensure_module_cached(self._module_hex)
        self._refresh_from_cache()

        # listen for push updates
        self._remove_listener = self._bridge.add_listener(self._handle_module_changed)

        # listen for connectivity changes
        self._remove_connection_listener = self._bridge.add_connection_listener(
            self._handle_connection_changed
        )

        # write initial state
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        if self._remove_connection_listener:
            self._remove_connection_listener()
            self._remove_connection_listener = None

    def _handle_connection_changed(self, connected: bool) -> None:
        self.async_write_ha_state()

    def _handle_module_changed(self, module_int: int) -> None:
        if module_int != self._module_int:
            return
        self._refresh_from_cache()
        self.async_write_ha_state()

    def _refresh_from_cache(self) -> None:
        level_pct = self._bridge.get_output_level_pct(self._module_int, self._output)
        if level_pct is None:
            # unknown -> keep last known, or mark off
            return
        self._is_on = level_pct > 0
        self._brightness = pct_to_ha(level_pct)

    async def async_turn_on(self, **kwargs) -> None:
        # HA brightness is 0..255; map to LiteTouch 0..100
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        level_pct = ha_to_pct(int(brightness))
        if ATTR_TRANSITION in kwargs:
            transition = kwargs[ATTR_TRANSITION]  # * 1000
            _LOGGER.debug("Transition passed: %s", transition)
        else:
            transition = self._default_transition

        await self._bridge.set_output_level(
            self._module_hex,
            self._output,
            level_pct,
            # self._loadid,
            transition=transition,
        )


    async def async_turn_off(self, **kwargs) -> None:
        if ATTR_TRANSITION in kwargs:
            transition = kwargs[ATTR_TRANSITION]  # * 1000
        else:
            transition = self._default_transition


        await self._bridge.set_output_level(
            self._module_hex,
            self._output,
            0,
            # self._loadid,
            transition=transition,
        )

