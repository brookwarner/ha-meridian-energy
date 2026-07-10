"""Phase 0 offline validation: exercise the read path against real data.

Usage:
    python3 scripts/dev_validate.py your-email@example.com

Prompts for the OTP code Meridian emails you. Writes nothing to Home Assistant.
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))

import aiohttp  # noqa: E402

from meridian_energy import const  # noqa: E402
from meridian_energy.auth import MeridianAuth  # noqa: E402
from meridian_energy.api import MeridianApi  # noqa: E402
from meridian_energy.statistics import (  # noqa: E402
    Baseline,
    NightWindow,
    build_statistics,
)


def _assert_invariants(series: dict[str, list[dict]]) -> None:
    energy_ids = {const.STAT_DAY, const.STAT_NIGHT, const.STAT_SOLAR}
    for sid, points in series.items():
        starts = [p["start"] for p in points]
        assert starts == sorted(starts), f"{sid}: not sorted"
        assert len(starts) == len(set(starts)), f"{sid}: duplicate hours"
        for p in points:
            assert p["start"].minute == 0 and p["start"].second == 0, f"{sid}: unaligned"
            assert p["start"].tzinfo is not None, f"{sid}: naive datetime"
        if sid in energy_ids:
            sums = [p["sum"] for p in points]
            assert sums == sorted(sums), f"{sid}: energy sum not monotonic"
    print("✓ all integrity invariants passed")


async def main(email: str) -> None:
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        print(f"Requesting OTP for {email} ...")
        journey_id = await auth.request_otp(email)
        otp = input("Enter the OTP code emailed to you: ").strip()
        bundle = await auth.validate_otp(email, otp, journey_id)
        print(f"✓ logged in; account {bundle.account_number}")

        api = MeridianApi(session, auth)
        account = await api.async_get_account()
        print(f"✓ property {account.property_id}; has_solar={account.has_solar}")

        cons = await api.async_get_recent(account.property_id, "CONSUMPTION", hours=168)
        gen = (
            await api.async_get_recent(account.property_id, "GENERATION", hours=168)
            if account.has_solar
            else []
        )
        print(f"fetched {len(cons)} consumption + {len(gen)} generation hours")
        if cons:
            sample = cons[0]
            print(f"  sample: {sample.start_utc.isoformat()} kwh={sample.kwh} cost={sample.cost}")

        window = NightWindow(const.DEFAULT_NIGHT_START, const.DEFAULT_NIGHT_END)
        series = build_statistics(cons + gen, window, None, {})
        _assert_invariants(series)

        for sid, points in series.items():
            if points:
                print(f"  {sid}: {len(points)} pts, last sum={points[-1]['sum']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 scripts/dev_validate.py <email>")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))
