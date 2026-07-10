"""Meridian Energy sensor (thin coordinator entity)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import const
from .coordinator import MeridianCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor from a config entry."""
    coordinator: MeridianCoordinator = entry.runtime_data
    async_add_entities([MeridianEnergyUsageSensor(coordinator)])


class MeridianEnergyUsageSensor(CoordinatorEntity[MeridianCoordinator], SensorEntity):
    """Surfaces import status; statistics are written by the coordinator."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:meter-electric"
    _attr_name = const.SENSOR_NAME

    def __init__(self, coordinator: MeridianCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = const.DOMAIN

    @property
    def native_value(self):
        """Return the latest imported day-consumption cumulative total."""
        data = self.coordinator.data
        if not data:
            return None
        return data.totals.get(const.STAT_DAY)

    @property
    def extra_state_attributes(self):
        """Return diagnostic attributes."""
        data = self.coordinator.data
        if not data:
            return {}
        attrs = {"account_number": data.account.account_number,
                 "has_solar": data.account.has_solar}
        if data.last_interval_start:
            attrs["last_interval_start"] = data.last_interval_start.isoformat()
        attrs.update(data.totals)
        return attrs
