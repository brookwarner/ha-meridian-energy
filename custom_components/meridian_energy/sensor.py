"""Meridian Energy sensors."""

from datetime import datetime, timedelta

import csv
from io import StringIO
from pytz import timezone
import logging
import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.components.sensor import SensorEntity

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.const import UnitOfEnergy
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
)

from .api import MeridianEnergyApi

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

NAME = DOMAIN
ISSUEURL = "https://github.com/codyc1515/ha-meridian-energy/issues"

STARTUP = f"""
-------------------------------------------------------------------
{NAME}
This is a custom component
If you have any issues with this you need to open an issue here:
{ISSUEURL}
-------------------------------------------------------------------
"""

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {vol.Required(CONF_EMAIL): cv.string, vol.Required(CONF_PASSWORD): cv.string}
)

SCAN_INTERVAL = timedelta(hours=3)  # Default to 3 hours


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    discovery_info=None,
):
    """Asynchronously set-up the entry."""
    email = entry.data.get(CONF_EMAIL)
    password = entry.data.get(CONF_PASSWORD)
    
    # Get configured rates with fallback to defaults
    day_rate = entry.data.get(CONF_DAY_RATE, DEFAULT_COST_RATE_DAY)
    night_rate = entry.data.get(CONF_NIGHT_RATE, DEFAULT_COST_RATE_NIGHT)
    solar_rate = entry.data.get(CONF_SOLAR_RATE, DEFAULT_COST_RATE_SOLAR)
    
    # Check for options updates
    if entry.options:
        day_rate = entry.options.get(CONF_DAY_RATE, day_rate)
        night_rate = entry.options.get(CONF_NIGHT_RATE, night_rate)
        solar_rate = entry.options.get(CONF_SOLAR_RATE, solar_rate)

    api = MeridianEnergyApi(email, password)

    _LOGGER.debug("Setting up sensor(s)...")

    sensors = []
    sensors.append(MeridianEnergyUsageSensor(SENSOR_NAME, api, day_rate, night_rate, solar_rate, entry.entry_id))
    async_add_entities(sensors, True)


class MeridianEnergyUsageSensor(SensorEntity):
    """Define Meridian Energy Usage sensor."""

    def __init__(self, name, api, day_rate, night_rate, solar_rate, entry_id):
        """Intialise Meridian Energy Usage sensor."""
        self._name = name
        self._icon = "mdi:meter-electric"
        self._state = 0
        self._unique_id = DOMAIN
        self._state_attributes = {}
        self._api = api
        self._day_rate = day_rate
        self._night_rate = night_rate
        self._solar_rate = solar_rate
        self._entry_id = entry_id

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return self._icon

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        attributes = dict(self._state_attributes)
        attributes.update({
            "day_rate": self._day_rate,
            "night_rate": self._night_rate,
            "solar_rate": self._solar_rate,
        })
        return attributes

    @property
    def unique_id(self):
        """Return the unique id."""
        return self._unique_id

    def update(self):
        """Update the sensor data."""
        _LOGGER.debug("Beginning usage update")

        solarStatistics = []
        solarRunningSum = 0
        solarCostStatistics = []
        solarCostRunningSum = 0

        dayStatistics = []
        dayRunningSum = 0
        dayCostStatistics = []
        dayCostRunningSum = 0

        nightStatistics = []
        nightRunningSum = 0
        nightCostStatistics = []
        nightCostRunningSum = 0

        # Login to the website
        self._api.token()

        # Get the latest usage data
        response = self._api.get_data()

        # Process the CSV consumption file
        csv_file = csv.reader(StringIO(response))

        for row in csv_file:
            # Accessing columns by index in each row
            if len(row) < 2:  # Checking if there are at least two columns
                _LOGGER.warning("Not enough columns in this row")
                break

            if row[0] == "HDR":
                _LOGGER.debug("HDR line arrived")
                continue
            elif row[0] == "DET":
                _LOGGER.debug("DET line arrived")

            # Row definitions from EIEP document 13A (https://www.ea.govt.nz/documents/182/EIEP_13A_Electricity_conveyed_information_for_consumers.pdf)
            energy_flow_direction = row[6]

            # Skip any estimated reads
            read_status = row[11]
            if read_status != "RD":
                _LOGGER.debug("HDR line skipped as its estimated")
                continue

            # Assuming row[9] contains the date in the format 'dd/mm/YYYY HH:MM:SS'
            read_period_start_date_time = row[9]

            # Assuming tz is your timezone (e.g., pytz.timezone('Your/Timezone'))
            tz = timezone("Pacific/Auckland")

            # Parse the date string into a datetime object
            start_date = datetime.strptime(
                read_period_start_date_time, "%d/%m/%Y %H:%M:%S"
            )

            # Exclude any readings that are at the 59th minute (summarised daily totals)
            if start_date.minute == 59:
                continue

            # Localize the datetime object
            start_date = tz.localize(start_date)

            # Round down to the nearest hour as HA can only handle hourly
            rounded_date = start_date.replace(minute=0, second=0, microsecond=0)

            # Only calculate the energy after all checks are complete
            unit_quantity_active_energy_volume = float(row[12])

            # Process solar export channels
            if energy_flow_direction == "I":
                solarRunningSum = solarRunningSum + unit_quantity_active_energy_volume
                solarStatistics.append(
                    StatisticData(start=rounded_date, sum=solarRunningSum)
                )
                
                # Calculate cost for solar export using configured rate
                solar_cost = unit_quantity_active_energy_volume * self._solar_rate
                solarCostRunningSum = solarCostRunningSum + solar_cost
                solarCostStatistics.append(
                    StatisticData(start=rounded_date, sum=solarCostRunningSum)
                )

            # Process regular channels
            else:
                # Night rate channel
                if (
                    start_date.hour >= 21 or
                    start_date.hour <= 6
                ):
                    nightRunningSum = nightRunningSum + unit_quantity_active_energy_volume
                    nightStatistics.append(
                        StatisticData(start=rounded_date, sum=nightRunningSum)
                    )
                    
                    # Calculate cost for night usage using configured rate
                    night_cost = unit_quantity_active_energy_volume * self._night_rate
                    nightCostRunningSum = nightCostRunningSum + night_cost
                    nightCostStatistics.append(
                        StatisticData(start=rounded_date, sum=nightCostRunningSum)
                    )

                # Day rate channel
                else:
                    dayRunningSum = dayRunningSum + unit_quantity_active_energy_volume
                    dayStatistics.append(
                        StatisticData(start=rounded_date, sum=dayRunningSum)
                    )
                    
                    # Calculate cost for day usage using configured rate
                    day_cost = unit_quantity_active_energy_volume * self._day_rate
                    dayCostRunningSum = dayCostRunningSum + day_cost
                    dayCostStatistics.append(
                        StatisticData(start=rounded_date, sum=dayCostRunningSum)
                    )

        # Add consumption statistics
        solarMetadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{SENSOR_NAME} (Solar Export)",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:return_to_grid",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        async_add_external_statistics(self.hass, solarMetadata, solarStatistics)

        dayMetadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{SENSOR_NAME} (Day)",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:consumption_day",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        async_add_external_statistics(self.hass, dayMetadata, dayStatistics)

        nightMetadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{SENSOR_NAME} (Night)",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:consumption_night",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        async_add_external_statistics(self.hass, nightMetadata, nightStatistics)
        
        # Add cost statistics
        solarCostMetadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{SENSOR_NAME} (Solar Export Cost)",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:return_to_grid_cost",
            unit_of_measurement="NZD",
        )
        async_add_external_statistics(self.hass, solarCostMetadata, solarCostStatistics)

        dayCostMetadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{SENSOR_NAME} (Day Cost)",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:consumption_day_cost",
            unit_of_measurement="NZD",
        )
        async_add_external_statistics(self.hass, dayCostMetadata, dayCostStatistics)

        nightCostMetadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{SENSOR_NAME} (Night Cost)",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:consumption_night_cost",
            unit_of_measurement="NZD",
        )
        async_add_external_statistics(self.hass, nightCostMetadata, nightCostStatistics)
