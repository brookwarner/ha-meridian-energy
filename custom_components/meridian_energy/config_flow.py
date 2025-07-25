"""Config flow for Meridian Energy integration."""

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    DOMAIN, 
    SENSOR_NAME, 
    CONF_DAY_RATE, 
    CONF_NIGHT_RATE, 
    CONF_SOLAR_RATE,
    DEFAULT_COST_RATE_DAY,
    DEFAULT_COST_RATE_NIGHT,
    DEFAULT_COST_RATE_SOLAR,
)


@config_entries.HANDLERS.register(DOMAIN)
class MeridianConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Define the config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return MeridianOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Show user form."""
        if user_input is not None:
            return self.async_create_entry(
                title=SENSOR_NAME,
                data={
                    CONF_EMAIL: user_input[CONF_EMAIL],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_DAY_RATE: user_input.get(CONF_DAY_RATE, DEFAULT_COST_RATE_DAY),
                    CONF_NIGHT_RATE: user_input.get(CONF_NIGHT_RATE, DEFAULT_COST_RATE_NIGHT),
                    CONF_SOLAR_RATE: user_input.get(CONF_SOLAR_RATE, DEFAULT_COST_RATE_SOLAR),
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): cv.string,
                    vol.Required(CONF_PASSWORD): cv.string,
                    vol.Optional(CONF_DAY_RATE, default=DEFAULT_COST_RATE_DAY): vol.Coerce(float),
                    vol.Optional(CONF_NIGHT_RATE, default=DEFAULT_COST_RATE_NIGHT): vol.Coerce(float),
                    vol.Optional(CONF_SOLAR_RATE, default=DEFAULT_COST_RATE_SOLAR): vol.Coerce(float),
                }
            ),
        )


class MeridianOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Meridian Energy integration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DAY_RATE,
                        default=self.config_entry.data.get(CONF_DAY_RATE, DEFAULT_COST_RATE_DAY),
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_NIGHT_RATE,
                        default=self.config_entry.data.get(CONF_NIGHT_RATE, DEFAULT_COST_RATE_NIGHT),
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_SOLAR_RATE,
                        default=self.config_entry.data.get(CONF_SOLAR_RATE, DEFAULT_COST_RATE_SOLAR),
                    ): vol.Coerce(float),
                }
            ),
        )
