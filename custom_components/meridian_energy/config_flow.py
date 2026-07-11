"""Config flow for Meridian Energy (email-OTP)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_EMAIL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import const
from .auth import MeridianAuth, MeridianAuthError, MeridianConnectionError


class MeridianConfigFlow(ConfigFlow, domain=const.DOMAIN):
    """Handle the OTP-based config flow."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialise transient flow state."""
        self._email: str | None = None
        self._journey_id: str | None = None
        self._auth: MeridianAuth | None = None
        self._reauth_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return MeridianOptionsFlowHandler()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Step 1: collect email and request an OTP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._auth = MeridianAuth(async_get_clientsession(self.hass))
            try:
                self._journey_id = await self._auth.request_otp(self._email)
            except MeridianConnectionError:
                errors["base"] = "cannot_connect"
            except MeridianAuthError:
                errors["base"] = "invalid_auth"
            else:
                return await self.async_step_otp()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_EMAIL): str}),
            errors=errors,
        )

    async def async_step_otp(self, user_input: dict[str, Any] | None = None):
        """Step 2: validate the OTP and create/update the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                bundle = await self._auth.validate_otp(
                    self._email, user_input["otp"], self._journey_id
                )
            except MeridianConnectionError:
                errors["base"] = "cannot_connect"
            except MeridianAuthError:
                errors["base"] = "invalid_otp"
            else:
                data = {
                    CONF_EMAIL: self._email,
                    const.CONF_REFRESH_TOKEN: bundle.refresh_token,
                    const.CONF_ACCOUNT_NUMBER: bundle.account_number,
                }
                if self._reauth_entry:
                    await self.async_set_unique_id(bundle.account_number)
                    if self._reauth_entry.unique_id is not None:
                        self._abort_if_unique_id_mismatch(reason="wrong_account")
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry, data=data, unique_id=bundle.account_number
                    )
                    await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
                await self.async_set_unique_id(bundle.account_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=const.SENSOR_NAME, data=data)
        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema({vol.Required("otp"): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        """Start reauth."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Reauth: re-request an OTP for the stored email."""
        if user_input is None and self._reauth_entry is not None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_EMAIL, default=self._reauth_entry.data.get(CONF_EMAIL)
                        ): str
                    }
                ),
            )
        return await self.async_step_user(user_input)


class MeridianOptionsFlowHandler(OptionsFlow):
    """Options: cost source, rates, and night window."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    const.CONF_USE_API_COST,
                    default=o.get(const.CONF_USE_API_COST, const.DEFAULT_USE_API_COST),
                ): bool,
                vol.Optional(
                    const.CONF_DAY_RATE,
                    default=o.get(const.CONF_DAY_RATE, const.DEFAULT_COST_RATE_DAY),
                ): vol.Coerce(float),
                vol.Optional(
                    const.CONF_NIGHT_RATE,
                    default=o.get(const.CONF_NIGHT_RATE, const.DEFAULT_COST_RATE_NIGHT),
                ): vol.Coerce(float),
                vol.Optional(
                    const.CONF_SOLAR_RATE,
                    default=o.get(const.CONF_SOLAR_RATE, const.DEFAULT_COST_RATE_SOLAR),
                ): vol.Coerce(float),
                vol.Optional(
                    const.CONF_NIGHT_START,
                    default=o.get(const.CONF_NIGHT_START, const.DEFAULT_NIGHT_START),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
                vol.Optional(
                    const.CONF_NIGHT_END,
                    default=o.get(const.CONF_NIGHT_END, const.DEFAULT_NIGHT_END),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
