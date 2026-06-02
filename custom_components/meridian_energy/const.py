"""Constants for the Meridian Energy sensors."""

from homeassistant.const import Platform

DOMAIN = "meridian_energy"
SENSOR_NAME = "Meridian Energy"

# Configuration keys
CONF_DAY_RATE = "day_rate"
CONF_NIGHT_RATE = "night_rate"
CONF_SOLAR_RATE = "solar_rate"

# Default cost rates per kWh (NZD)
DEFAULT_COST_RATE_DAY = 0.2308
DEFAULT_COST_RATE_NIGHT = 0.2308
DEFAULT_COST_RATE_SOLAR = 0.0  # No cost for solar export, could be negative if there's a feed-in tariff

# Legacy constants for backward compatibility
COST_RATE_DAY = DEFAULT_COST_RATE_DAY
COST_RATE_NIGHT = DEFAULT_COST_RATE_NIGHT
COST_RATE_SOLAR = DEFAULT_COST_RATE_SOLAR

PLATFORMS = [
    Platform.SENSOR,
]
