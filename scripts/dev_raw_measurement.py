"""Debug: dump RAW measurement nodes from Meridian to inspect the cost field.

Usage:
    python3 scripts/dev_raw_measurement.py your-email@example.com

Requires: aiohttp (pip install aiohttp); Home Assistant is NOT required.

Prompts for the OTP code Meridian emails you. Read-only; writes nothing.
Prints the raw JSON of the first few hourly measurement nodes so we can see the
exact shape of metaData.statistics[].costInclTax.estimatedAmount (cents vs
dollars, single vs multiple entries).
"""

import asyncio
import importlib.abc
import importlib.machinery
import json
import sys
import types
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))


# --- Robust homeassistant auto-mock (same pattern as dev_validate.py) ---
class _MockModule(types.ModuleType):
    """A module that fabricates missing attributes as MagicMock() on-demand."""

    def __getattr__(self, name):
        mock = MagicMock()
        setattr(self, name, mock)
        return mock


class _HomeAssistantMetaPathFinder(importlib.abc.MetaPathFinder):
    """Find and load homeassistant.* imports by synthesizing mock modules."""

    def find_spec(self, fullname, path, target=None):
        if fullname == "homeassistant" or fullname.startswith("homeassistant."):
            return importlib.machinery.ModuleSpec(fullname, _HomeAssistantLoader())
        return None


class _HomeAssistantLoader(importlib.abc.Loader):
    """Loader that creates _MockModule instances for homeassistant.* imports."""

    def create_module(self, spec):
        mod = _MockModule(spec.name)
        mod.__path__ = []
        return mod

    def exec_module(self, module):
        pass


if not any(isinstance(f, _HomeAssistantMetaPathFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _HomeAssistantMetaPathFinder())

import aiohttp  # noqa: E402

from meridian_energy.api import MeridianApi, _MEASUREMENTS_QUERY  # noqa: E402
from meridian_energy.auth import MeridianAuth  # noqa: E402


async def main(email: str) -> None:
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        print(f"Requesting OTP for {email} ...")
        journey_id = await auth.request_otp(email)
        otp = input("Enter the OTP code emailed to you: ").strip()
        await auth.validate_otp(email, otp, journey_id)
        print(f"✓ logged in; account {auth.account_number}")

        api = MeridianApi(session, auth)
        account = await api.async_get_account()

        variables = {
            "accountNumber": auth.account_number,
            "propertyId": account.property_id,
            "after": None,
            "last": 3,
            "endOn": date.today().isoformat(),
            "readingFrequencyType": "HOUR_INTERVAL",
            "readingDirectionType": "CONSUMPTION",
            "readingQualityType": "ACTUAL",
        }
        data = await api._graphql("measurements", _MEASUREMENTS_QUERY, variables)
        edges = data["account"]["property"]["measurements"]["edges"]
        print(f"\n=== raw nodes ({len(edges)}) ===")
        for edge in edges:
            print(json.dumps(edge["node"], indent=2))
            print("-" * 40)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 scripts/dev_raw_measurement.py <email>")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))
