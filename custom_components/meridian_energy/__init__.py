"""The Meridian Energy integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import const
from .api import MeridianApi
from .auth import MeridianAuth
from .coordinator import MeridianCoordinator

_LOGGER = logging.getLogger(__name__)
_PLATFORMS = list(const.PLATFORMS)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Meridian Energy from a config entry."""
    refresh_token = entry.data.get(const.CONF_REFRESH_TOKEN)
    if not refresh_token:
        raise ConfigEntryAuthFailed("Meridian now requires a one-time code sign-in")

    session = async_get_clientsession(hass)
    auth = MeridianAuth(session, refresh_token=refresh_token)
    # Seed the account number from stored config so the first query works.
    auth._account_number = entry.data.get(const.CONF_ACCOUNT_NUMBER)
    api = MeridianApi(session, auth)

    options = {**entry.data, **entry.options}
    coordinator = MeridianCoordinator(hass, api, options)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old v1 (email/password) entries to v2 (OTP)."""
    if entry.version < 2:
        # v1 stored email+password; v2 uses an OTP-obtained refresh token.
        # We cannot derive a token from a password, so keep the email, drop the
        # rest, bump to v2, and let async_setup_entry raise ConfigEntryAuthFailed
        # to start the OTP reauth flow. Statistics history is unaffected (keyed
        # by statistic_id, not the entry).
        new_data = {CONF_EMAIL: entry.data.get(CONF_EMAIL)}
        hass.config_entries.async_update_entry(entry, data=new_data, version=2)
    return True
