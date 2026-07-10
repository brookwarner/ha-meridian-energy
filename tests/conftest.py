"""Shared test fixtures."""
import sys
import types
from pathlib import Path

# Make the custom_components package importable as a top-level module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))

# Stub the `homeassistant` package so pure, HA-free modules (e.g.
# statistics.py) can be imported and unit-tested without installing the
# full `homeassistant` dependency (which is not compatible with this
# environment's Python version). Importing `meridian_energy.<anything>`
# still executes the package's __init__.py and const.py, which import a
# handful of homeassistant symbols at module scope, so those are stubbed
# here. This does not affect production behavior — it only exists for the
# test collection process.
if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")

    ha_core = types.ModuleType("homeassistant.core")
    ha_core.HomeAssistant = type("HomeAssistant", (), {})

    ha_config_entries = types.ModuleType("homeassistant.config_entries")
    ha_config_entries.ConfigEntry = type("ConfigEntry", (), {})

    ha_const = types.ModuleType("homeassistant.const")

    class Platform:
        SENSOR = "sensor"

    ha_const.Platform = Platform

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.const"] = ha_const
