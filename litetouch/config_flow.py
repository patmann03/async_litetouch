"""Config flow for LiteTouch integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import selector

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

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=10001): int,
        vol.Optional(CONF_COMMAND_CONNECTIONS, default=4): int,
        vol.Optional(CONF_EVENT_CONNECTION, default=True): bool,
        vol.Optional(CONF_TRANSITION, default=1): int,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    # For now, just return the data. In a real implementation, you might test the connection.
    return data


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LiteTouch."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Get the options flow for this handler."""
        return OptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title="LiteTouch", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


def _validate_lights(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate a list of lights."""

    for item in value:
        if item.get(CONF_LOADID) is None and (
            item.get(CONF_MODULE) is None or item.get(CONF_OUTPUT) is None
        ):
            raise vol.Invalid(
                "Each light must define either loadid, or both module and output"
            )

    for item in value:
        if CONF_LOADID in item:
            try:
                item[CONF_LOADID] = int(item[CONF_LOADID])
            except (ValueError, TypeError) as err:
                raise vol.Invalid(f"{CONF_LOADID} must be an integer") from err
        if CONF_OUTPUT in item:
            try:
                item[CONF_OUTPUT] = int(item[CONF_OUTPUT])
            except (ValueError, TypeError) as err:
                raise vol.Invalid(f"{CONF_OUTPUT} must be an integer") from err

    return value


LIGHT_SELECTOR = {
    "object": {
        "multiple": True,
        "fields": {
            CONF_NAME: {"selector": {"text": {}}, "required": True},
            CONF_MODULE: {"selector": {"text": {}}},
            CONF_OUTPUT: {"selector": {"number": {"min": 0, "step": 1}}},
            CONF_LOADID: {"selector": {"number": {"min": 0, "step": 1}}},
            CONF_STATION: {"selector": {"text": {}}},
            CONF_BUTTON: {"selector": {"text": {}}},
            CONF_LOCATION: {"selector": {"text": {}}},
            CONF_FLOOR: {"selector": {"text": {}}},
            CONF_LTCODE: {"selector": {"text": {}}},
        },
    }
}


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for LiteTouch."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # store config entry privately; OptionsFlow provides a read-only property.
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            lights = user_input.get(CONF_LIGHTS, [])
            try:
                _validate_lights(lights)
            except vol.Invalid as err:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._get_schema(),
                    errors={CONF_LIGHTS: str(err)},
                )

            return self.async_create_entry(title="", data={CONF_LIGHTS: lights})

        return self.async_show_form(
            step_id="init",
            data_schema=self._get_schema(),
        )

    def _get_schema(self) -> vol.Schema:
        options = self._config_entry.options
        lights = options.get(CONF_LIGHTS, [])

        return vol.Schema(
            {
                vol.Optional(
                    CONF_LIGHTS,
                    default=lights,
                ): selector(LIGHT_SELECTOR),
            }
        )
