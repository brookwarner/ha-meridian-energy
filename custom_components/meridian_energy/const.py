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

# --- New API (Kraken / Firebase CIAM) ---
CIAM_API_KEY = "AIzaSyCYCKXQhGmo7haJxAAyO_7mIPrV7jtxsK8"
BRAND = "meridian"
TZ = "Pacific/Auckland"

APP_ORIGIN = "https://app.meridianenergy.nz"
AUTH_BASE = "https://auth.meridianenergy.nz"
EMAIL_CONNECTOR_URL = f"{AUTH_BASE}/cf/email-connector"
EMAIL_OTP_URL = f"{AUTH_BASE}/cf/email-otp-authenticator"
SIGNIN_CUSTOM_TOKEN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"
)
SECURETOKEN_URL = "https://securetoken.googleapis.com/v1/token"
GRAPHQL_URL = "https://api.meridianenergy.nz/v1/graphql/"

TOKEN_EXPIRY_MARGIN = 120  # seconds before expiry to proactively refresh

# --- Config / options keys ---
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCOUNT_NUMBER = "account_number"
CONF_NIGHT_START = "night_start_hour"
CONF_NIGHT_END = "night_end_hour"
CONF_USE_API_COST = "use_api_cost"

DEFAULT_NIGHT_START = 21
DEFAULT_NIGHT_END = 7
DEFAULT_USE_API_COST = True

# --- Statistic IDs (MUST match existing recorder rows) ---
STAT_DAY = f"{DOMAIN}:consumption_day"
STAT_NIGHT = f"{DOMAIN}:consumption_night"
STAT_SOLAR = f"{DOMAIN}:return_to_grid"
STAT_DAY_COST = f"{DOMAIN}:consumption_day_cost"
STAT_NIGHT_COST = f"{DOMAIN}:consumption_night_cost"
STAT_SOLAR_COST = f"{DOMAIN}:return_to_grid_cost"

UNIT_ENERGY = "kWh"
UNIT_COST = "NZD"
