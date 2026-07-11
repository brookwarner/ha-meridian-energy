# Meridian Energy New API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the integration from the dead `secure.meridianenergy.co.nz` CSV portal to the new Kraken/Firebase app (`app.meridianenergy.nz` + `api.meridianenergy.nz/v1/graphql`), with correct, continuous Home Assistant long-term statistics.

**Architecture:** Async integration. `auth.py` handles Firebase email-OTP login + token refresh; `api.py` is a GraphQL client; `statistics.py` is a pure, HA-free transform that turns measurements into cumulative statistics with strong integrity guarantees; `coordinator.py` orchestrates fetch + statistics import; `sensor.py` is a thin coordinator entity; `config_flow.py` is a two-step OTP flow. A standalone `scripts/dev_validate.py` exercises the whole read path against real data with zero HA writes.

**Tech Stack:** Python 3.11+, aiohttp (HA core dep), stdlib `zoneinfo`/`uuid`/`base64`/`json`, Home Assistant `DataUpdateCoordinator` + `async_add_external_statistics`. Tests: pytest, pytest-asyncio, aioresponses, freezegun (no full HA needed for the core modules).

## Global Constraints

- Preserve these exact statistic IDs and units (must never change): `meridian_energy:consumption_day` (kWh), `meridian_energy:consumption_night` (kWh), `meridian_energy:return_to_grid` (kWh), `meridian_energy:consumption_day_cost` (NZD), `meridian_energy:consumption_night_cost` (NZD), `meridian_energy:return_to_grid_cost` (NZD). All `has_sum=True`, `has_mean=False`.
- Firebase CIAM Web API key (public): `AIzaSyCYCKXQhGmo7haJxAAyO_7mIPrV7jtxsK8`.
- Brand string: `meridian`. Timezone for bucketing: `Pacific/Auckland`.
- Energy (kWh) statistic sums MUST be monotonic non-decreasing and continue from the recorder's existing last sum — never reset to 0 while prior data exists. Cost (NZD) sums are cumulative but MAY decrease (solar credits).
- Only import finalized hours: `readingQualityType=ACTUAL`, and skip any hour whose `endAt` is in the future.
- No new pip runtime requirements (JWT is decoded manually; aiohttp is core). `manifest.json` `requirements` stays `[]`.
- Never deploy to the production HA instance without explicit user confirmation. The dev instance for Phase 1 is a disposable Docker HA seeded from a *copy* of the DB.
- DOMAIN stays `meridian_energy`. Config unique_id = account number.

---

## File Structure

- `custom_components/meridian_energy/const.py` — MODIFY: add auth/URL/config/statistic-id constants.
- `custom_components/meridian_energy/statistics.py` — CREATE: pure transform (`Interval`, `NightWindow`, `Baseline`, `Rates`, `build_statistics`, `is_night`).
- `custom_components/meridian_energy/auth.py` — CREATE: `MeridianAuth`, `TokenBundle`, error types.
- `custom_components/meridian_energy/api.py` — REWRITE: `MeridianApi`, `Account`, `Register`, `RawInterval`, GraphQL query constants.
- `custom_components/meridian_energy/coordinator.py` — CREATE: `MeridianCoordinator`, `CoordinatorData`.
- `custom_components/meridian_energy/sensor.py` — REWRITE: thin `CoordinatorEntity`.
- `custom_components/meridian_energy/config_flow.py` — REWRITE: two-step OTP flow + options + reauth.
- `custom_components/meridian_energy/__init__.py` — MODIFY: runtime_data wiring.
- `custom_components/meridian_energy/manifest.json` — MODIFY: version bump, loggers.
- `custom_components/meridian_energy/strings.json` + `translations/en.json` — CREATE: flow UI text.
- `scripts/dev_validate.py` — CREATE: Phase 0 offline harness.
- `scripts/dev_compare_stats.py` — CREATE: Phase 0.5 DB baseline + diff.
- `tests/` — CREATE: `test_statistics.py`, `test_auth.py`, `test_api.py`, plus `requirements-test.txt`, `pytest.ini`.

---

## Task 0: Dev/test harness setup

**Files:**
- Create: `tests/requirements-test.txt`, `pytest.ini`, `tests/__init__.py`, `tests/conftest.py`
- Modify: `custom_components/meridian_energy/manifest.json`

**Interfaces:**
- Produces: a working `python3 -m pytest` run; version-bumped manifest.

- [ ] **Step 1: Create test requirements**

`tests/requirements-test.txt`:
```
pytest==8.3.4
pytest-asyncio==0.25.2
aioresponses==0.7.8
freezegun==1.5.1
```

- [ ] **Step 2: Create pytest config**

`pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
```

- [ ] **Step 3: Create empty package + conftest**

`tests/__init__.py`: empty file.
`tests/conftest.py`:
```python
"""Shared test fixtures."""
import sys
from pathlib import Path

# Make the custom_components package importable as a top-level module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))
```

- [ ] **Step 4: Install and verify**

Run: `python3 -m pip install -r tests/requirements-test.txt && python3 -m pytest --co -q`
Expected: pytest collects 0 tests, exits 5 (no tests yet) or 0 — no import/config errors.

- [ ] **Step 5: Bump manifest version + add loggers**

In `custom_components/meridian_energy/manifest.json` set `"version": "2.0.0"` and add `"loggers": ["custom_components.meridian_energy"]`.

- [ ] **Step 6: Commit**

```bash
git add tests/requirements-test.txt pytest.ini tests/__init__.py tests/conftest.py custom_components/meridian_energy/manifest.json
git commit -m "chore: add test harness and bump version to 2.0.0"
```

---

## Task 1: Constants

**Files:**
- Modify: `custom_components/meridian_energy/const.py`

**Interfaces:**
- Produces: constants consumed by every later task (URLs, keys, statistic IDs, config keys, defaults).

- [ ] **Step 1: Append new constants**

Add to `const.py` (keep all existing content):
```python
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
```

- [ ] **Step 2: Verify import**

Run: `python3 -c "import sys; sys.path.insert(0,'custom_components'); from meridian_energy import const; print(const.STAT_DAY, const.CIAM_API_KEY[:6])"`
Expected: `meridian_energy:consumption_day AIzaSy`

- [ ] **Step 3: Commit**

```bash
git add custom_components/meridian_energy/const.py
git commit -m "feat: add new-API constants and statistic IDs"
```

---

## Task 2: Statistics transform — bucketing, ordering, dedup, DST

**Files:**
- Create: `custom_components/meridian_energy/statistics.py`
- Test: `tests/test_statistics.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Interval(start_utc: datetime, local_hour: int, kwh: float, direction: str, cost: float | None)` — `direction` is `"consumption"` or `"generation"`; `start_utc` is tz-aware UTC at top of hour.
  - `@dataclass(frozen=True) NightWindow(start_hour: int, end_hour: int)`
  - `is_night(local_hour: int, window: NightWindow) -> bool`
  - `bucket_of(interval: Interval, window: NightWindow) -> tuple[str, str]` returning `(energy_statistic_id, cost_statistic_id)`.

- [ ] **Step 1: Write failing tests for is_night + bucket_of**

`tests/test_statistics.py`:
```python
from datetime import datetime, timezone
from meridian_energy import const
from meridian_energy.statistics import Interval, NightWindow, is_night, bucket_of

W = NightWindow(const.DEFAULT_NIGHT_START, const.DEFAULT_NIGHT_END)  # 21..7

def _iv(local_hour, direction="consumption", kwh=1.0, cost=0.1):
    # start_utc value is irrelevant for these two functions
    return Interval(datetime(2026, 6, 1, 0, tzinfo=timezone.utc), local_hour, kwh, direction, cost)

def test_is_night_wraps_midnight():
    for h in [21, 22, 23, 0, 3, 6]:
        assert is_night(h, W) is True
    for h in [7, 8, 12, 20]:
        assert is_night(h, W) is False

def test_is_night_non_wrapping_window():
    w = NightWindow(1, 5)  # night = 1,2,3,4
    assert is_night(2, w) is True
    assert is_night(0, w) is False
    assert is_night(5, w) is False

def test_bucket_of_day_night_solar():
    assert bucket_of(_iv(10), W) == (const.STAT_DAY, const.STAT_DAY_COST)
    assert bucket_of(_iv(23), W) == (const.STAT_NIGHT, const.STAT_NIGHT_COST)
    assert bucket_of(_iv(10, direction="generation"), W) == (
        const.STAT_SOLAR, const.STAT_SOLAR_COST,
    )
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_statistics.py -v`
Expected: FAIL — `ModuleNotFoundError: meridian_energy.statistics`.

- [ ] **Step 3: Implement statistics.py (partial)**

`custom_components/meridian_energy/statistics.py`:
```python
"""Pure, Home-Assistant-free transform from measurements to statistics.

All functions here are deterministic and side-effect free so they can be
unit-tested without Home Assistant or the network, and reused by the dev
validation harness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from . import const

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Interval:
    """One finalized hourly measurement."""

    start_utc: datetime  # tz-aware UTC, aligned to top of hour
    local_hour: int  # 0-23, local Pacific/Auckland hour at start
    kwh: float
    direction: str  # "consumption" | "generation"
    cost: float | None  # API estimated cost incl tax, or None


@dataclass(frozen=True)
class NightWindow:
    """Local-hour window that counts as 'night'."""

    start_hour: int
    end_hour: int


@dataclass(frozen=True)
class Rates:
    """Manual override rates ($/kWh)."""

    day: float
    night: float
    solar: float


@dataclass(frozen=True)
class Baseline:
    """The last statistic point already stored for a statistic_id."""

    last_sum: float
    last_start_utc: datetime | None


def is_night(local_hour: int, window: NightWindow) -> bool:
    """Return True if local_hour falls in the night window (may wrap midnight)."""
    if window.start_hour > window.end_hour:  # wraps midnight, e.g. 21..7
        return local_hour >= window.start_hour or local_hour < window.end_hour
    return window.start_hour <= local_hour < window.end_hour


def bucket_of(interval: Interval, window: NightWindow) -> tuple[str, str]:
    """Return (energy_statistic_id, cost_statistic_id) for an interval."""
    if interval.direction == "generation":
        return (const.STAT_SOLAR, const.STAT_SOLAR_COST)
    if is_night(interval.local_hour, window):
        return (const.STAT_NIGHT, const.STAT_NIGHT_COST)
    return (const.STAT_DAY, const.STAT_DAY_COST)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python3 -m pytest tests/test_statistics.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/meridian_energy/statistics.py tests/test_statistics.py
git commit -m "feat: statistics bucketing + night-window logic"
```

---

## Task 3: Statistics transform — cumulative sums, continuity, cost, guards

**Files:**
- Modify: `custom_components/meridian_energy/statistics.py`
- Test: `tests/test_statistics.py`

**Interfaces:**
- Consumes: `Interval`, `NightWindow`, `Rates`, `Baseline`, `bucket_of` from Task 2.
- Produces:
  - `build_statistics(intervals: list[Interval], window: NightWindow, rates: Rates | None, baselines: dict[str, Baseline]) -> dict[str, list[dict]]`
    - Returns `{statistic_id: [{"start": datetime, "sum": float}, ...]}` for all six IDs (energy + cost).
    - Energy sums are monotonic non-decreasing, continue from `baselines`, append-only for hours strictly after `baseline.last_start_utc`.
    - Cost uses API `cost` when `rates is None`, else `kwh * rate`; cost sums are cumulative (may decrease).

- [ ] **Step 1: Write failing tests for build_statistics**

Append to `tests/test_statistics.py`:
```python
from datetime import timedelta
from meridian_energy.statistics import Rates, Baseline, build_statistics

def _uiv(h_utc, local_hour, direction="consumption", kwh=1.0, cost=0.5):
    start = datetime(2026, 6, 1, h_utc, tzinfo=timezone.utc)
    return Interval(start, local_hour, kwh, direction, cost)

def test_build_continues_from_baseline_never_resets():
    base = datetime(2026, 6, 1, 0, tzinfo=timezone.utc)
    ivs = [_uiv(1, 10, kwh=2.0), _uiv(2, 11, kwh=3.0)]
    baselines = {const.STAT_DAY: Baseline(100.0, base)}
    out = build_statistics(ivs, W, None, baselines)
    sums = [p["sum"] for p in out[const.STAT_DAY]]
    assert sums == [102.0, 105.0]  # continues from 100, not 0

def test_build_first_run_starts_at_zero_baseline():
    out = build_statistics([_uiv(1, 10, kwh=2.0)], W, None, {})
    assert out[const.STAT_DAY][0]["sum"] == 2.0

def test_build_is_monotonic_and_sorted_even_if_input_unordered():
    ivs = [_uiv(3, 12, kwh=1.0), _uiv(1, 10, kwh=1.0), _uiv(2, 11, kwh=1.0)]
    out = build_statistics(ivs, W, None, {})
    starts = [p["start"] for p in out[const.STAT_DAY]]
    sums = [p["sum"] for p in out[const.STAT_DAY]]
    assert starts == sorted(starts)
    assert sums == [1.0, 2.0, 3.0]

def test_build_dedups_duplicate_hours_last_wins():
    ivs = [_uiv(1, 10, kwh=1.0), _uiv(1, 10, kwh=5.0)]
    out = build_statistics(ivs, W, None, {})
    assert len(out[const.STAT_DAY]) == 1
    assert out[const.STAT_DAY][0]["sum"] == 5.0

def test_build_skips_already_imported_hours():
    base = datetime(2026, 6, 1, 1, tzinfo=timezone.utc)
    ivs = [_uiv(1, 10, kwh=9.0), _uiv(2, 11, kwh=3.0)]  # hour 1 already imported
    out = build_statistics(ivs, W, None, {const.STAT_DAY: Baseline(50.0, base)})
    assert [p["sum"] for p in out[const.STAT_DAY]] == [53.0]

def test_build_rejects_negative_energy():
    out = build_statistics([_uiv(1, 10, kwh=-4.0), _uiv(2, 11, kwh=2.0)], W, None, {})
    assert [p["sum"] for p in out[const.STAT_DAY]] == [2.0]

def test_build_cost_uses_api_estimate_by_default():
    out = build_statistics([_uiv(1, 10, kwh=2.0, cost=0.75)], W, None, {})
    assert out[const.STAT_DAY_COST][0]["sum"] == 0.75

def test_build_cost_uses_override_rates_when_provided():
    rates = Rates(day=0.30, night=0.20, solar=0.05)
    out = build_statistics([_uiv(1, 10, kwh=2.0, cost=0.75)], W, rates, {})
    assert out[const.STAT_DAY_COST][0]["sum"] == 0.60  # 2.0 * 0.30

def test_build_cost_falls_back_to_zero_when_no_estimate_and_no_rates():
    out = build_statistics([_uiv(1, 10, kwh=2.0, cost=None)], W, None, {})
    assert out[const.STAT_DAY_COST][0]["sum"] == 0.0

def test_solar_generation_routed_to_return_to_grid():
    out = build_statistics([_uiv(1, 10, direction="generation", kwh=1.5)], W, None, {})
    assert out[const.STAT_SOLAR][0]["sum"] == 1.5
    assert out[const.STAT_DAY] == []
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_statistics.py -k build -v`
Expected: FAIL — `build_statistics` not defined.

- [ ] **Step 3: Implement build_statistics**

Append to `statistics.py`:
```python
ALL_ENERGY_IDS = (const.STAT_DAY, const.STAT_NIGHT, const.STAT_SOLAR)
ALL_COST_IDS = (const.STAT_DAY_COST, const.STAT_NIGHT_COST, const.STAT_SOLAR_COST)


def _rate_for(cost_id: str, rates: Rates) -> float:
    if cost_id == const.STAT_DAY_COST:
        return rates.day
    if cost_id == const.STAT_NIGHT_COST:
        return rates.night
    return rates.solar


def build_statistics(
    intervals: list[Interval],
    window: NightWindow,
    rates: Rates | None,
    baselines: dict[str, Baseline],
) -> dict[str, list[dict]]:
    """Turn intervals into continuous cumulative statistics per statistic_id.

    Energy sums continue from the recorder baseline and are monotonic;
    only hours strictly after the baseline's last hour are appended.
    Cost sums are cumulative and may decrease (e.g. solar credits).
    """
    # Group deduplicated (last-wins) intervals per energy bucket.
    grouped: dict[str, dict[datetime, Interval]] = {sid: {} for sid in ALL_ENERGY_IDS}
    for iv in intervals:
        energy_id, _ = bucket_of(iv, window)
        grouped[energy_id][iv.start_utc] = iv  # last occurrence wins

    result: dict[str, list[dict]] = {sid: [] for sid in (*ALL_ENERGY_IDS, *ALL_COST_IDS)}

    for energy_id in ALL_ENERGY_IDS:
        cost_id = {
            const.STAT_DAY: const.STAT_DAY_COST,
            const.STAT_NIGHT: const.STAT_NIGHT_COST,
            const.STAT_SOLAR: const.STAT_SOLAR_COST,
        }[energy_id]

        e_base = baselines.get(energy_id, Baseline(0.0, None))
        c_base = baselines.get(cost_id, Baseline(0.0, None))
        e_running = e_base.last_sum
        c_running = c_base.last_sum

        for start in sorted(grouped[energy_id]):
            iv = grouped[energy_id][start]
            if e_base.last_start_utc is not None and start <= e_base.last_start_utc:
                continue  # already imported
            if iv.kwh < 0:
                _LOGGER.warning(
                    "Skipping negative energy %.3f at %s for %s", iv.kwh, start, energy_id
                )
                continue
            e_running += iv.kwh
            result[energy_id].append({"start": start, "sum": round(e_running, 3)})

            if rates is not None:
                cost = iv.kwh * _rate_for(cost_id, rates)
            elif iv.cost is not None:
                cost = iv.cost
            else:
                cost = 0.0
            c_running += cost
            result[cost_id].append({"start": start, "sum": round(c_running, 4)})

    return result
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python3 -m pytest tests/test_statistics.py -v`
Expected: all passed (13).

- [ ] **Step 5: Add DST-boundary test**

Append to `tests/test_statistics.py`:
```python
from zoneinfo import ZoneInfo

def test_dst_autumn_boundary_two_local_2am_hours_are_distinct_points():
    # NZDT->NZST 2026-04-05: local 02:00 occurs twice (offset +13 then +12).
    tz = ZoneInfo(const.TZ)
    inst1 = datetime(2026, 4, 5, 2, 0, tzinfo=tz, fold=0).astimezone(timezone.utc)
    inst2 = datetime(2026, 4, 5, 2, 0, tzinfo=tz, fold=1).astimezone(timezone.utc)
    assert inst1 != inst2  # sanity: two distinct instants
    ivs = [
        Interval(inst1, 2, 1.0, "consumption", 0.1),
        Interval(inst2, 2, 1.0, "consumption", 0.1),
    ]
    out = build_statistics(ivs, W, None, {})
    # Both are night (hour 2), distinct instants -> two monotonic points.
    assert [p["sum"] for p in out[const.STAT_NIGHT]] == [1.0, 2.0]
```

- [ ] **Step 6: Run tests, verify pass**

Run: `python3 -m pytest tests/test_statistics.py -v`
Expected: all passed (14).

- [ ] **Step 7: Commit**

```bash
git add custom_components/meridian_energy/statistics.py tests/test_statistics.py
git commit -m "feat: continuous monotonic statistics with cost + guards"
```

---

## Task 4: Firebase OTP auth client

**Files:**
- Create: `custom_components/meridian_energy/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `const` (URLs, CIAM key, margin).
- Produces:
  - `class MeridianAuthError(Exception)` (bad OTP / revoked → reauth), `class MeridianConnectionError(Exception)` (retryable).
  - `@dataclass TokenBundle(id_token: str, refresh_token: str, account_number: str, expires_at: float)`
  - `class MeridianAuth(session: aiohttp.ClientSession, refresh_token: str | None = None)` with:
    - `async request_otp(email: str) -> str` (returns journey_id)
    - `async validate_otp(email: str, otp: str, journey_id: str) -> TokenBundle`
    - `async async_valid_token() -> str` (refreshes using stored refresh_token if within margin of expiry)
    - properties `refresh_token: str | None`, `account_number: str | None`
    - `staticmethod decode_claims(id_token: str) -> dict`

- [ ] **Step 1: Write failing tests**

`tests/test_auth.py`:
```python
import base64
import json
import time

import aiohttp
import pytest
from aioresponses import aioresponses

from meridian_energy import const
from meridian_energy.auth import MeridianAuth, MeridianAuthError


def _fake_id_token(account="A-F53DF172", exp=None):
    exp = exp or int(time.time()) + 3600
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload = {
        "accounts": [{"brand": "MERIDIAN_ENERGY", "account_number": account}],
        "exp": exp,
        "user_id": "U-1",
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


async def test_request_otp_returns_journey_id():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        with aioresponses() as m:
            m.post(const.EMAIL_CONNECTOR_URL, status=200, payload={"status": "ok"})
            jid = await auth.request_otp("me@example.com")
        assert isinstance(jid, str) and len(jid) > 10


async def test_validate_otp_exchanges_custom_token_and_decodes_account():
    idt = _fake_id_token()
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        with aioresponses() as m:
            m.post(const.EMAIL_OTP_URL, status=200, payload={"customToken": "CT"})
            m.post(
                f"{const.SIGNIN_CUSTOM_TOKEN_URL}?key={const.CIAM_API_KEY}",
                status=200,
                payload={"idToken": idt, "refreshToken": "RT", "expiresIn": "3600"},
            )
            bundle = await auth.validate_otp("me@example.com", "123456", "jid")
        assert bundle.refresh_token == "RT"
        assert bundle.account_number == "A-F53DF172"
        assert auth.refresh_token == "RT"


async def test_validate_otp_bad_code_raises_auth_error():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        with aioresponses() as m:
            m.post(const.EMAIL_OTP_URL, status=401, payload={"error": "invalid otp"})
            with pytest.raises(MeridianAuthError):
                await auth.validate_otp("me@example.com", "000000", "jid")


async def test_valid_token_refreshes_when_expired():
    expired = _fake_id_token(exp=int(time.time()) - 10)
    fresh = _fake_id_token(exp=int(time.time()) + 3600)
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session, refresh_token="RT0")
        auth._id_token = expired  # seed an expired token
        auth._expires_at = time.time() - 10
        with aioresponses() as m:
            m.post(
                f"{const.SECURETOKEN_URL}?key={const.CIAM_API_KEY}",
                status=200,
                payload={"id_token": fresh, "refresh_token": "RT1", "expires_in": "3600"},
            )
            token = await auth.async_valid_token()
        assert token == fresh
        assert auth.refresh_token == "RT1"  # rotation stored


async def test_valid_token_refresh_failure_raises_auth_error():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session, refresh_token="BAD")
        with aioresponses() as m:
            m.post(
                f"{const.SECURETOKEN_URL}?key={const.CIAM_API_KEY}",
                status=400,
                payload={"error": {"message": "TOKEN_EXPIRED"}},
            )
            with pytest.raises(MeridianAuthError):
                await auth.async_valid_token()
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: meridian_energy.auth`.

- [ ] **Step 3: Implement auth.py**

`custom_components/meridian_energy/auth.py`:
```python
"""Firebase (Meridian CIAM) email-OTP authentication client."""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass

import aiohttp

from . import const

_LOGGER = logging.getLogger(__name__)

_JSON_HEADERS = {"content-type": "application/json", "X-Client-Platform": "web"}


class MeridianAuthError(Exception):
    """Auth failed in a way that needs user re-authentication."""


class MeridianConnectionError(Exception):
    """Transient network/server error; retry later."""


@dataclass
class TokenBundle:
    """Result of a successful login."""

    id_token: str
    refresh_token: str
    account_number: str
    expires_at: float


class MeridianAuth:
    """Owns the Firebase token lifecycle."""

    def __init__(
        self, session: aiohttp.ClientSession, refresh_token: str | None = None
    ) -> None:
        """Initialise with an aiohttp session and optional stored refresh token."""
        self._session = session
        self._refresh_token = refresh_token
        self._id_token: str | None = None
        self._expires_at: float = 0.0
        self._account_number: str | None = None

    @property
    def refresh_token(self) -> str | None:
        """Return the current (possibly rotated) refresh token."""
        return self._refresh_token

    @property
    def account_number(self) -> str | None:
        """Return the account number decoded from the last id token."""
        return self._account_number

    @staticmethod
    def decode_claims(id_token: str) -> dict:
        """Decode a JWT payload without verifying the signature."""
        try:
            payload_b64 = id_token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)  # restore padding
            return json.loads(base64.urlsafe_b64decode(payload_b64))
        except (IndexError, ValueError) as err:
            raise MeridianAuthError(f"Could not decode id token: {err}") from err

    async def request_otp(self, email: str) -> str:
        """Trigger Meridian to email a one-time code; return the journey id."""
        journey_id = str(uuid.uuid4())
        payload = {
            "email": email,
            "brand": const.BRAND,
            "journeyId": journey_id,
            "otpEnabled": True,
            "redirectUrl": f"{const.APP_ORIGIN}/login",
        }
        try:
            async with self._session.post(
                const.EMAIL_CONNECTOR_URL, json=payload, headers=_JSON_HEADERS
            ) as resp:
                if resp.status >= 500:
                    raise MeridianConnectionError(f"OTP request server error {resp.status}")
                if resp.status >= 400:
                    raise MeridianAuthError(f"OTP request rejected ({resp.status})")
        except aiohttp.ClientError as err:
            raise MeridianConnectionError(str(err)) from err
        return journey_id

    async def validate_otp(self, email: str, otp: str, journey_id: str) -> TokenBundle:
        """Validate the OTP, exchange the custom token, return an id/refresh bundle."""
        payload = {"email": email, "otp": otp, "brand": const.BRAND, "journeyId": journey_id}
        try:
            async with self._session.post(
                const.EMAIL_OTP_URL, json=payload, headers=_JSON_HEADERS
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400 or not data.get("customToken"):
                    raise MeridianAuthError(
                        f"OTP validation failed ({resp.status}): {data.get('error')}"
                    )
            custom_token = data["customToken"]
            return await self._exchange_custom_token(custom_token)
        except aiohttp.ClientError as err:
            raise MeridianConnectionError(str(err)) from err

    async def _exchange_custom_token(self, custom_token: str) -> TokenBundle:
        url = f"{const.SIGNIN_CUSTOM_TOKEN_URL}?key={const.CIAM_API_KEY}"
        async with self._session.post(
            url, json={"token": custom_token, "returnSecureToken": True}
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                raise MeridianAuthError(f"Custom-token exchange failed: {data.get('error')}")
        self._store_tokens(data["idToken"], data["refreshToken"], data.get("expiresIn", "3600"))
        return TokenBundle(
            id_token=self._id_token,
            refresh_token=self._refresh_token,
            account_number=self._account_number,
            expires_at=self._expires_at,
        )

    async def async_valid_token(self) -> str:
        """Return a currently-valid id token, refreshing if near expiry."""
        if self._id_token and time.time() < self._expires_at - const.TOKEN_EXPIRY_MARGIN:
            return self._id_token
        await self._refresh()
        return self._id_token

    async def _refresh(self) -> None:
        if not self._refresh_token:
            raise MeridianAuthError("No refresh token available; re-authentication required")
        url = f"{const.SECURETOKEN_URL}?key={const.CIAM_API_KEY}"
        data = {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
        try:
            async with self._session.post(url, data=data) as resp:
                body = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise MeridianAuthError(f"Token refresh failed: {body.get('error')}")
        except aiohttp.ClientError as err:
            raise MeridianConnectionError(str(err)) from err
        # securetoken endpoint uses snake_case keys.
        self._store_tokens(body["id_token"], body["refresh_token"], body.get("expires_in", "3600"))

    def _store_tokens(self, id_token: str, refresh_token: str, expires_in) -> None:
        self._id_token = id_token
        self._refresh_token = refresh_token
        self._expires_at = time.time() + int(expires_in)
        claims = self.decode_claims(id_token)
        accounts = claims.get("accounts") or []
        if accounts:
            self._account_number = accounts[0].get("account_number")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python3 -m pytest tests/test_auth.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/meridian_energy/auth.py tests/test_auth.py
git commit -m "feat: Firebase email-OTP auth client with token refresh"
```

---

## Task 5: GraphQL API client

**Files:**
- Rewrite: `custom_components/meridian_energy/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `MeridianAuth` (Task 4), `Interval` (Task 2), `const`.
- Produces:
  - `class MeridianApiError(Exception)`
  - `@dataclass Register(identifier: str, is_feed_in: bool)`
  - `@dataclass Account(account_number: str, property_id: str, has_solar: bool, registers: list[Register])`
  - `class MeridianApi(session, auth)` with:
    - `async async_get_account() -> Account`
    - `async async_get_measurements(property_id: str, direction: str, end_on: date, last: int, after: str | None = None) -> tuple[list[Interval], str | None]` (returns page of intervals + next cursor; `direction` in `{"CONSUMPTION","GENERATION"}`)
    - `async async_get_recent(property_id: str, direction: str, hours: int) -> list[Interval]` (paginates, returns Interval list mapped to Task 2 `Interval`)

- [ ] **Step 1: Write failing tests**

`tests/test_api.py`:
```python
from datetime import date

import aiohttp
from aioresponses import aioresponses

from meridian_energy import const
from meridian_energy.api import MeridianApi
from meridian_energy.auth import MeridianAuth


class _StubAuth(MeridianAuth):
    def __init__(self):
        pass  # bypass base init for tests

    async def async_valid_token(self):
        return "TESTTOKEN"


def _measurements_payload(edges, has_next=False, end_cursor=None):
    return {
        "data": {
            "account": {
                "id": "acc1",
                "property": {
                    "id": "349524",
                    "measurements": {
                        "__typename": "MeasurementConnection",
                        "pageInfo": {
                            "hasNextPage": has_next,
                            "hasPreviousPage": False,
                            "startCursor": "s",
                            "endCursor": end_cursor,
                        },
                        "edges": edges,
                    },
                },
            }
        }
    }


def _edge(value, start_at, end_at, cost=0.5):
    return {
        "node": {
            "source": "SMART_METER",
            "value": value,
            "unit": "kWh",
            "readAt": start_at,
            "startAt": start_at,
            "endAt": end_at,
            "metaData": {
                "statistics": [
                    {"label": "Cost", "type": "COST", "value": None,
                     "costInclTax": {"estimatedAmount": cost}}
                ]
            },
        }
    }


async def test_get_account_parses_property_and_solar():
    payload = {
        "data": {
            "account": {
                "number": "A-F53DF172",
                "id": "acc1",
                "properties": [
                    {
                        "id": "349524",
                        "address": "1 Test St",
                        "meterPoints": [
                            {
                                "id": "mp1",
                                "registers": [
                                    {"identifier": "R1", "isFeedIn": False},
                                    {"identifier": "R2", "isFeedIn": True},
                                ],
                            }
                        ],
                    }
                ],
            }
        }
    }
    async with aiohttp.ClientSession() as session:
        api = MeridianApi(session, _StubAuth())
        with aioresponses() as m:
            m.post(
                f"{const.GRAPHQL_URL}?opName=account", status=200, payload=payload
            )
            acc = await api.async_get_account()
    assert acc.account_number == "A-F53DF172"
    assert acc.property_id == "349524"
    assert acc.has_solar is True


async def test_get_measurements_maps_intervals_utc_and_localhour():
    edges = [_edge("2.5", "2026-06-01T10:00:00+12:00", "2026-06-01T11:00:00+12:00", cost=0.7)]
    async with aiohttp.ClientSession() as session:
        api = MeridianApi(session, _StubAuth())
        with aioresponses() as m:
            m.post(
                f"{const.GRAPHQL_URL}?opName=measurements",
                status=200,
                payload=_measurements_payload(edges),
            )
            intervals, cursor = await api.async_get_measurements(
                "349524", "CONSUMPTION", date(2026, 6, 2), 168
            )
    assert len(intervals) == 1
    iv = intervals[0]
    assert iv.kwh == 2.5
    assert iv.local_hour == 10
    assert iv.direction == "consumption"
    assert iv.cost == 0.7
    assert iv.start_utc.utcoffset().total_seconds() == 0
    assert iv.start_utc.hour == 22  # 10:00+12:00 == 22:00Z previous handling


async def test_get_recent_paginates_until_no_next_page():
    page1 = _measurements_payload(
        [_edge("1", "2026-06-01T09:00:00+12:00", "2026-06-01T10:00:00+12:00")],
        has_next=True, end_cursor="CUR1",
    )
    page2 = _measurements_payload(
        [_edge("1", "2026-06-01T08:00:00+12:00", "2026-06-01T09:00:00+12:00")],
        has_next=False, end_cursor=None,
    )
    async with aiohttp.ClientSession() as session:
        api = MeridianApi(session, _StubAuth())
        with aioresponses() as m:
            m.post(f"{const.GRAPHQL_URL}?opName=measurements", status=200, payload=page1)
            m.post(f"{const.GRAPHQL_URL}?opName=measurements", status=200, payload=page2)
            intervals = await api.async_get_recent("349524", "CONSUMPTION", hours=336)
    assert len(intervals) == 2
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: FAIL — new `MeridianApi` signature/module not present.

- [ ] **Step 3: Implement api.py**

Replace `custom_components/meridian_energy/api.py` entirely:
```python
"""Meridian Energy GraphQL API client (new Kraken platform)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp

from . import const
from .auth import MeridianAuth, MeridianConnectionError
from .statistics import Interval

_LOGGER = logging.getLogger(__name__)
_TZ = ZoneInfo(const.TZ)

# GraphQL documents (verbatim selection sets used by the live app).
_ACCOUNT_QUERY = """
query account($accountNumber: String!, $activeFrom: DateTime) {
  account(accountNumber: $accountNumber) {
    number
    id
    properties(activeFrom: $activeFrom) {
      id
      address
      meterPoints {
        id
        registers { identifier isFeedIn }
      }
    }
  }
}
""".strip()

_MEASUREMENTS_QUERY = """
query measurements($accountNumber: String!, $propertyId: ID!, $after: String, $last: Int, $endOn: Date, $readingFrequencyType: ReadingFrequencyType!, $readingDirectionType: ReadingDirectionType, $readingQualityType: ReadingQualityType) {
  account(accountNumber: $accountNumber) {
    id
    property(id: $propertyId) {
      id
      measurements(after: $after, last: $last, endOn: $endOn, timezone: "Pacific/Auckland", utilityFilters: [{electricityFilters: {readingDirection: $readingDirectionType, readingQuality: $readingQualityType, readingFrequencyType: $readingFrequencyType}}]) {
        ... on MeasurementConnection {
          pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
          edges {
            node {
              source value unit readAt
              ... on IntervalMeasurementType { startAt endAt }
              metaData { statistics { label type value costInclTax { estimatedAmount } } }
            }
          }
        }
      }
    }
  }
}
""".strip()


class MeridianApiError(Exception):
    """A GraphQL query failed."""


@dataclass
class Register:
    """A meter register."""

    identifier: str
    is_feed_in: bool


@dataclass
class Account:
    """Account bootstrap data."""

    account_number: str
    property_id: str
    has_solar: bool
    registers: list[Register]


class MeridianApi:
    """GraphQL client for the new Meridian API."""

    def __init__(self, session: aiohttp.ClientSession, auth: MeridianAuth) -> None:
        """Initialise with an aiohttp session and an auth client."""
        self._session = session
        self._auth = auth

    async def _graphql(self, op_name: str, query: str, variables: dict) -> dict:
        """Execute a GraphQL operation, refreshing the token once on 401."""
        for attempt in range(2):
            token = await self._auth.async_valid_token()
            headers = {
                "authorization": token,
                "content-type": "application/json",
                "origin": const.APP_ORIGIN,
                "referer": f"{const.APP_ORIGIN}/",
            }
            body = {"operationName": op_name, "variables": variables, "query": query}
            try:
                async with self._session.post(
                    f"{const.GRAPHQL_URL}?opName={op_name}", json=body, headers=headers
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        self._auth._expires_at = 0  # force refresh, retry once
                        continue
                    data = await resp.json(content_type=None)
            except aiohttp.ClientError as err:
                raise MeridianConnectionError(str(err)) from err
            if data.get("errors"):
                raise MeridianApiError(str(data["errors"]))
            return data["data"]
        raise MeridianApiError("Unauthorized after token refresh")

    async def async_get_account(self) -> Account:
        """Fetch account number, first property id, and solar/register info."""
        account_number = self._auth.account_number
        data = await self._graphql(
            "account",
            _ACCOUNT_QUERY,
            {"accountNumber": account_number, "activeFrom": "1970-01-01T00:00:00.000Z"},
        )
        account = data["account"]
        properties = account.get("properties") or []
        if not properties:
            raise MeridianApiError("No properties on account")
        prop = properties[0]
        registers: list[Register] = []
        for mp in prop.get("meterPoints") or []:
            for reg in mp.get("registers") or []:
                registers.append(Register(reg["identifier"], bool(reg.get("isFeedIn"))))
        return Account(
            account_number=account.get("number") or account_number,
            property_id=prop["id"],
            has_solar=any(r.is_feed_in for r in registers),
            registers=registers,
        )

    async def async_get_measurements(
        self,
        property_id: str,
        direction: str,
        end_on: date,
        last: int,
        after: str | None = None,
    ) -> tuple[list[Interval], str | None]:
        """Fetch one page of hourly measurements; return (intervals, next_cursor)."""
        variables = {
            "accountNumber": self._auth.account_number,
            "propertyId": property_id,
            "after": after,
            "last": last,
            "endOn": end_on.isoformat(),
            "readingFrequencyType": "HOUR_INTERVAL",
            "readingDirectionType": direction,
            "readingQualityType": "ACTUAL",
        }
        data = await self._graphql("measurements", _MEASUREMENTS_QUERY, variables)
        conn = data["account"]["property"]["measurements"]
        intervals = [
            iv
            for edge in conn.get("edges", [])
            if (iv := self._map_node(edge["node"], direction)) is not None
        ]
        page = conn.get("pageInfo") or {}
        next_cursor = page.get("endCursor") if page.get("hasNextPage") else None
        return intervals, next_cursor

    async def async_get_recent(
        self, property_id: str, direction: str, hours: int
    ) -> list[Interval]:
        """Paginate measurements covering roughly the last `hours` hours."""
        end_on = date.today()
        collected: list[Interval] = []
        after: str | None = None
        remaining = hours
        while remaining > 0:
            page_size = min(remaining, 168)
            intervals, after = await self.async_get_measurements(
                property_id, direction, end_on, page_size, after
            )
            collected.extend(intervals)
            remaining -= page_size
            if after is None:
                break
        return collected

    @staticmethod
    def _map_node(node: dict, direction: str) -> Interval | None:
        """Convert a GraphQL node to an Interval, or None if unusable."""
        start_raw = node.get("startAt")
        end_raw = node.get("endAt")
        if not start_raw or not end_raw:
            return None
        start_local = datetime.fromisoformat(start_raw)
        end_local = datetime.fromisoformat(end_raw)
        now = datetime.now(timezone.utc)
        if end_local.astimezone(timezone.utc) > now:
            return None  # skip the in-progress / future hour
        start_utc = start_local.astimezone(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        local_hour = start_local.astimezone(_TZ).hour
        try:
            kwh = float(node["value"])
        except (TypeError, ValueError):
            return None
        cost = MeridianApi._extract_cost(node)
        return Interval(
            start_utc=start_utc,
            local_hour=local_hour,
            kwh=kwh,
            direction="generation" if direction == "GENERATION" else "consumption",
            cost=cost,
        )

    @staticmethod
    def _extract_cost(node: dict) -> float | None:
        """Sum estimated cost-incl-tax across statistics entries, if present."""
        stats = (node.get("metaData") or {}).get("statistics") or []
        total = None
        for entry in stats:
            incl = entry.get("costInclTax") or {}
            amount = incl.get("estimatedAmount")
            if amount is not None:
                total = (total or 0.0) + float(amount)
        return total
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: 3 passed. (If `test_get_measurements_maps_intervals_utc_and_localhour` asserts the wrong UTC hour, correct the expected value to match `10:00+12:00 → 22:00Z` of the *previous* day: `iv.start_utc.hour == 22`.)

- [ ] **Step 5: Commit**

```bash
git add custom_components/meridian_energy/api.py tests/test_api.py
git commit -m "feat: GraphQL API client (account + measurements + pagination)"
```

---

## Task 6: Phase 0 offline validation harness

**Files:**
- Create: `scripts/dev_validate.py`

**Interfaces:**
- Consumes: `MeridianAuth`, `MeridianApi`, `build_statistics`, `NightWindow`, `Baseline`.
- Produces: a runnable CLI that logs in via OTP, fetches real data, runs the transform, asserts invariants, prints series. No HA writes.

- [ ] **Step 1: Implement the harness**

`scripts/dev_validate.py`:
```python
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
```

- [ ] **Step 2: Syntax check**

Run: `python3 -m py_compile scripts/dev_validate.py && echo OK`
Expected: `OK`

- [ ] **Step 3: Live run (requires user OTP) — VALIDATION GATE**

Run: `python3 scripts/dev_validate.py <user-email>`
Expected: logs in, prints property/solar, fetches hours, prints a sample interval, `✓ all integrity invariants passed`.
**This is where the two live-data unknowns are confirmed:** verify the printed `cost=` is non-None and plausible (else fix `_extract_cost`), and that `has_solar` matches reality. If the OTP endpoints return a different shape, adjust `auth.py` accordingly and re-run.

- [ ] **Step 4: Commit**

```bash
git add scripts/dev_validate.py
git commit -m "feat: Phase 0 offline validation harness"
```

---

## Task 7: Phase 0.5 statistics baseline + history diff

**Files:**
- Create: `scripts/dev_compare_stats.py`

**Interfaces:**
- Consumes: a local read-only copy of `home-assistant_v2.db`.
- Produces: prints existing statistic IDs, units, last sums (the continuity baselines), and — for an overlapping window — a diff of new-pipeline hourly kWh vs stored values.

- [ ] **Step 1: Copy the recorder DB read-only**

Run:
```bash
mkdir -p /tmp/meridian_val && scp haos:/config/home-assistant_v2.db /tmp/meridian_val/ha.db && ls -la /tmp/meridian_val/ha.db
```
Expected: a ~500 MB `ha.db` copied locally. (Read-only copy; the live DB is untouched.)

- [ ] **Step 2: Implement the comparison script**

`scripts/dev_compare_stats.py`:
```python
"""Phase 0.5: read existing Meridian statistics from a DB copy.

Usage: python3 scripts/dev_compare_stats.py /tmp/meridian_val/ha.db

Read-only. Prints each meridian statistic's unit and last cumulative sum
(the continuity baseline the integration must continue from).
"""

import sqlite3
import sys
from datetime import datetime, timezone


def main(db_path: str) -> None:
    con = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT id, statistic_id, unit_of_measurement, has_sum "
        "FROM statistics_meta WHERE statistic_id LIKE 'meridian_energy:%' ORDER BY statistic_id"
    )
    metas = cur.fetchall()
    if not metas:
        print("No meridian_energy statistics found in this DB.")
        return
    print(f"{'statistic_id':<40} {'unit':<6} {'last_sum':>14} last_start(UTC)")
    for meta_id, sid, unit, has_sum in metas:
        cur.execute(
            "SELECT start_ts, sum FROM statistics WHERE metadata_id=? "
            "ORDER BY start_ts DESC LIMIT 1",
            (meta_id,),
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            last_start = datetime.fromtimestamp(row[0], tz=timezone.utc).isoformat()
            last_sum = row[1]
        else:
            last_start, last_sum = "-", None
        print(f"{sid:<40} {unit or '-':<6} {str(last_sum):>14} {last_start}")
    con.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 scripts/dev_compare_stats.py <path-to-ha.db>")
        raise SystemExit(2)
    main(sys.argv[1])
```

- [ ] **Step 3: Run it — VALIDATION GATE**

Run: `python3 scripts/dev_compare_stats.py /tmp/meridian_val/ha.db`
Expected: a table of the six `meridian_energy:*` statistic IDs with their units and last sums. **Confirm the IDs and units match the Global Constraints exactly** — this proves the rewrite will continue existing series rather than create new ones. If any ID is missing, note whether that series simply has no history yet (fine) vs a mismatched name (must reconcile).

- [ ] **Step 4: Commit**

```bash
git add scripts/dev_compare_stats.py
git commit -m "feat: Phase 0.5 statistics baseline reader"
```

---

## Task 8: Coordinator (fetch + statistics import)

**Files:**
- Create: `custom_components/meridian_energy/coordinator.py`

**Interfaces:**
- Consumes: `MeridianApi`, `MeridianAuth`, `build_statistics`, `Baseline`, `NightWindow`, `Rates`.
- Produces:
  - `@dataclass CoordinatorData(account: Account, totals: dict[str, float], last_interval_start: datetime | None)`
  - `class MeridianCoordinator(DataUpdateCoordinator[CoordinatorData])` with `__init__(hass, api, options: dict)` and `async _async_update_data()`.
  - Reads baselines via `recorder.statistics.get_last_statistics`, writes via `async_add_external_statistics`.

- [ ] **Step 1: Implement coordinator.py**

`custom_components/meridian_energy/coordinator.py`:
```python
"""Coordinator: fetch measurements and import continuous statistics."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import const
from .api import Account, MeridianApi, MeridianApiError
from .auth import MeridianAuthError, MeridianConnectionError
from .statistics import Baseline, NightWindow, Rates, build_statistics

_LOGGER = logging.getLogger(__name__)
_UPDATE_INTERVAL = timedelta(hours=3)
_FETCH_HOURS = 168  # one week per run; append-only dedupe handles overlap

_STAT_NAMES = {
    const.STAT_DAY: "Meridian Energy (Day)",
    const.STAT_NIGHT: "Meridian Energy (Night)",
    const.STAT_SOLAR: "Meridian Energy (Solar Export)",
    const.STAT_DAY_COST: "Meridian Energy (Day Cost)",
    const.STAT_NIGHT_COST: "Meridian Energy (Night Cost)",
    const.STAT_SOLAR_COST: "Meridian Energy (Solar Export Cost)",
}
_ENERGY_IDS = (const.STAT_DAY, const.STAT_NIGHT, const.STAT_SOLAR)


@dataclass
class CoordinatorData:
    """State surfaced to the sensor entity."""

    account: Account
    totals: dict[str, float]
    last_interval_start: datetime | None


class MeridianCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Fetches data and imports statistics."""

    def __init__(self, hass: HomeAssistant, api: MeridianApi, options: dict) -> None:
        """Initialise the coordinator."""
        super().__init__(hass, _LOGGER, name=const.DOMAIN, update_interval=_UPDATE_INTERVAL)
        self._api = api
        self._options = options
        self._account: Account | None = None

    def _night_window(self) -> NightWindow:
        return NightWindow(
            int(self._options.get(const.CONF_NIGHT_START, const.DEFAULT_NIGHT_START)),
            int(self._options.get(const.CONF_NIGHT_END, const.DEFAULT_NIGHT_END)),
        )

    def _rates(self) -> Rates | None:
        if self._options.get(const.CONF_USE_API_COST, const.DEFAULT_USE_API_COST):
            return None
        return Rates(
            day=float(self._options.get(const.CONF_DAY_RATE, const.DEFAULT_COST_RATE_DAY)),
            night=float(self._options.get(const.CONF_NIGHT_RATE, const.DEFAULT_COST_RATE_NIGHT)),
            solar=float(self._options.get(const.CONF_SOLAR_RATE, const.DEFAULT_COST_RATE_SOLAR)),
        )

    async def _async_update_data(self) -> CoordinatorData:
        try:
            if self._account is None:
                self._account = await self._api.async_get_account()
            account = self._account
            cons = await self._api.async_get_recent(
                account.property_id, "CONSUMPTION", _FETCH_HOURS
            )
            gen = (
                await self._api.async_get_recent(
                    account.property_id, "GENERATION", _FETCH_HOURS
                )
                if account.has_solar
                else []
            )
        except MeridianAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (MeridianConnectionError, MeridianApiError) as err:
            raise UpdateFailed(str(err)) from err

        baselines = await self._async_read_baselines()
        series = build_statistics(cons + gen, self._night_window(), self._rates(), baselines)

        totals: dict[str, float] = {}
        for sid, points in series.items():
            if not points:
                continue
            metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=_STAT_NAMES[sid],
                source=const.DOMAIN,
                statistic_id=sid,
                unit_of_measurement=(
                    const.UNIT_ENERGY if sid in _ENERGY_IDS else const.UNIT_COST
                ),
            )
            stat_data = [StatisticData(start=p["start"], sum=p["sum"]) for p in points]
            async_add_external_statistics(self.hass, metadata, stat_data)
            totals[sid] = points[-1]["sum"]

        last_start = max(
            (iv.start_utc for iv in cons + gen), default=None
        )
        return CoordinatorData(account=account, totals=totals, last_interval_start=last_start)

    async def _async_read_baselines(self) -> dict[str, Baseline]:
        """Read the last stored sum + start for each statistic_id."""
        recorder = get_instance(self.hass)
        baselines: dict[str, Baseline] = {}
        for sid in (*_ENERGY_IDS, const.STAT_DAY_COST, const.STAT_NIGHT_COST, const.STAT_SOLAR_COST):
            last = await recorder.async_add_executor_job(
                get_last_statistics, self.hass, 1, sid, True, {"sum"}
            )
            rows = last.get(sid) if last else None
            if rows:
                row = rows[0]
                start = datetime.fromtimestamp(row["start"], tz=timezone.utc) if isinstance(
                    row["start"], (int, float)
                ) else row["start"]
                baselines[sid] = Baseline(last_sum=row["sum"] or 0.0, last_start_utc=start)
        return baselines
```

- [ ] **Step 2: Syntax check**

Run: `python3 -m py_compile custom_components/meridian_energy/coordinator.py && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add custom_components/meridian_energy/coordinator.py
git commit -m "feat: coordinator with baseline-continuing statistics import"
```

---

## Task 9: Sensor entity

**Files:**
- Rewrite: `custom_components/meridian_energy/sensor.py`

**Interfaces:**
- Consumes: `MeridianCoordinator`, `CoordinatorData`.
- Produces: one `MeridianEnergyUsageSensor(CoordinatorEntity)` added via `async_setup_entry`.

- [ ] **Step 1: Rewrite sensor.py**

`custom_components/meridian_energy/sensor.py`:
```python
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
    async_add_entities([MeridianEnergyUsageSensor(coordinator, entry)])


class MeridianEnergyUsageSensor(CoordinatorEntity[MeridianCoordinator], SensorEntity):
    """Surfaces import status; statistics are written by the coordinator."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:meter-electric"
    _attr_name = const.SENSOR_NAME

    def __init__(self, coordinator: MeridianCoordinator, entry: ConfigEntry) -> None:
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
```

- [ ] **Step 2: Syntax check**

Run: `python3 -m py_compile custom_components/meridian_energy/sensor.py && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add custom_components/meridian_energy/sensor.py
git commit -m "feat: thin coordinator-based sensor entity"
```

---

## Task 10: Config flow (two-step OTP + options + reauth)

**Files:**
- Rewrite: `custom_components/meridian_energy/config_flow.py`
- Create: `custom_components/meridian_energy/strings.json`, `custom_components/meridian_energy/translations/en.json`

**Interfaces:**
- Consumes: `MeridianAuth`, `MeridianAuthError`, `MeridianConnectionError`, `const`.
- Produces: `MeridianConfigFlow` (steps: user → otp; reauth → reauth_confirm) and `MeridianOptionsFlowHandler`.

- [ ] **Step 1: Rewrite config_flow.py**

`custom_components/meridian_energy/config_flow.py`:
```python
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
        return MeridianOptionsFlowHandler(config_entry)

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
                    self.hass.config_entries.async_update_entry(self._reauth_entry, data=data)
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
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Reauth: re-request an OTP for the stored email."""
        if user_input is None and self._reauth_entry is not None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required(CONF_EMAIL): str}),
            )
        return await self.async_step_user(user_input)


class MeridianOptionsFlowHandler(OptionsFlow):
    """Options: cost source, rates, and night window."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Store the entry."""
        self.config_entry = config_entry

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
```

- [ ] **Step 2: Create strings.json**

`custom_components/meridian_energy/strings.json`:
```json
{
  "config": {
    "step": {
      "user": {
        "title": "Meridian Energy",
        "description": "Enter your Meridian account email. A one-time code will be emailed to you.",
        "data": { "email": "Email" }
      },
      "otp": {
        "title": "Enter code",
        "description": "Enter the one-time code Meridian just emailed to you.",
        "data": { "otp": "One-time code" }
      },
      "reauth_confirm": {
        "title": "Re-authenticate",
        "description": "Your login expired. Enter your email to receive a new code.",
        "data": { "email": "Email" }
      }
    },
    "error": {
      "cannot_connect": "Could not reach Meridian. Try again.",
      "invalid_auth": "Could not start login for that email.",
      "invalid_otp": "That code was not accepted. Try again."
    },
    "abort": {
      "already_configured": "This account is already configured.",
      "reauth_successful": "Re-authentication was successful."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Meridian Energy options",
        "data": {
          "use_api_cost": "Use Meridian's estimated costs (uncheck to use manual rates)",
          "day_rate": "Day rate ($/kWh, manual)",
          "night_rate": "Night rate ($/kWh, manual)",
          "solar_rate": "Solar export rate ($/kWh, manual)",
          "night_start_hour": "Night starts at hour (0-23)",
          "night_end_hour": "Night ends at hour (0-23)"
        }
      }
    }
  }
}
```

- [ ] **Step 3: Copy to translations/en.json**

Run: `mkdir -p custom_components/meridian_energy/translations && cp custom_components/meridian_energy/strings.json custom_components/meridian_energy/translations/en.json`

- [ ] **Step 4: Syntax + JSON check**

Run: `python3 -m py_compile custom_components/meridian_energy/config_flow.py && python3 -m json.tool custom_components/meridian_energy/strings.json >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add custom_components/meridian_energy/config_flow.py custom_components/meridian_energy/strings.json custom_components/meridian_energy/translations/en.json
git commit -m "feat: two-step OTP config flow with options and reauth"
```

---

## Task 11: Integration setup (`__init__.py`)

**Files:**
- Modify: `custom_components/meridian_energy/__init__.py`

**Interfaces:**
- Consumes: `MeridianAuth`, `MeridianApi`, `MeridianCoordinator`.
- Produces: `entry.runtime_data = MeridianCoordinator`; standard setup/unload/reload.

- [ ] **Step 1: Rewrite __init__.py**

`custom_components/meridian_energy/__init__.py`:
```python
"""The Meridian Energy integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import const
from .api import MeridianApi
from .auth import MeridianAuth
from .coordinator import MeridianCoordinator

_LOGGER = logging.getLogger(__name__)
_PLATFORMS = list(const.PLATFORMS)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Meridian Energy from a config entry."""
    session = async_get_clientsession(hass)
    auth = MeridianAuth(session, refresh_token=entry.data[const.CONF_REFRESH_TOKEN])
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
```

Note: `async_valid_token()` refreshes on first use, which repopulates `_account_number` from the fresh token; the seeded value covers the very first call ordering.

- [ ] **Step 2: Syntax check**

Run: `python3 -m py_compile custom_components/meridian_energy/__init__.py && echo OK`
Expected: `OK`

- [ ] **Step 3: Full test suite + lint**

Run: `python3 -m pytest -q && ruff check custom_components/meridian_energy`
Expected: all tests pass; ruff reports no errors (fix any that appear).

- [ ] **Step 4: Commit**

```bash
git add custom_components/meridian_energy/__init__.py
git commit -m "feat: wire runtime_data coordinator setup for new API"
```

---

## Task 12: Phase 1 isolated-instance validation

**Files:** none (operational validation).

**Interfaces:**
- Consumes: the whole integration + a disposable HA seeded from a DB copy.

- [ ] **Step 1: Prepare a disposable HA config dir seeded with a DB copy**

Run:
```bash
mkdir -p /tmp/meridian_ha/config
cp /tmp/meridian_val/ha.db /tmp/meridian_ha/config/home-assistant_v2.db
mkdir -p /tmp/meridian_ha/config/custom_components
cp -r custom_components/meridian_energy /tmp/meridian_ha/config/custom_components/
```

- [ ] **Step 2: Launch pinned HA in Docker**

Run:
```bash
docker run --rm -p 8123:8123 -v /tmp/meridian_ha/config:/config --name meridian_test ghcr.io/home-assistant/home-assistant:2026.6
```
Expected: HA starts and serves http://localhost:8123. Complete onboarding (throwaway account).

- [ ] **Step 3: Add the integration and complete OTP — VALIDATION GATE**

In the UI: Settings → Devices & Services → Add Integration → "Meridian Energy" → enter email → enter the OTP. Expected: entry created, sensor appears.

- [ ] **Step 4: Verify statistics continuity — VALIDATION GATE**

In the UI: Developer Tools → Statistics (no "issues" for the six IDs), and Settings → Dashboards → Energy → add the Meridian consumption/return statistics. Watch the graph render. **Confirm: no spikes, no negative bars, no reset-to-zero at the boundary between old (DB copy) history and newly imported hours.** Cross-check the last sums against `dev_compare_stats.py` output — the new points must continue upward from those baselines.

- [ ] **Step 5: Stop the disposable instance**

Run: `docker stop meridian_test`

- [ ] **Step 6: Record the result**

Append a short "Phase 1 validated on <date>: continuity confirmed" note to the spec's Validation section and commit.

---

## Task 13: Production rollout (gated on explicit user confirmation)

**Files:** none (deployment).

- [ ] **Step 1: Get explicit go-ahead** from the user to deploy to the live instance. Do not proceed otherwise.

- [ ] **Step 2: Back up the live instance**

Run: `ssh haos "ha backups new --name meridian-pre-migration"`
Expected: a new backup slug is printed.

- [ ] **Step 3: Deploy the updated component**

Run:
```bash
ssh haos "cd /config && [ -d .git ] && git pull || true"
scp -r custom_components/meridian_energy haos:/config/custom_components/
```
(Whichever matches the user's install method — HACS update or direct copy.)

- [ ] **Step 4: Restart and re-authenticate**

Run: `ssh haos "ha core restart"`, wait, then in the UI reconfigure the Meridian entry (the old email/password entry must be removed and re-added via OTP; statistics history is preserved because it is keyed by statistic_id).

- [ ] **Step 5: Verify in production — VALIDATION GATE**

Run: `ssh haos "ha core logs | grep -i meridian | tail -30"` (no errors) and check the Energy dashboard renders continuously. If anything looks wrong, restore the backup: `ssh haos "ha backups restore <slug>"`.

---

## Self-Review Notes

- **Spec coverage:** auth (T4), GraphQL data (T5), day/night configurable (T2/T3/T10), cost API-default+override (T3/T10), full async coordinator (T8), statistics continuity + integrity guarantees (T3, tests), validation phases 0/0.5/1/2 (T6/T7/T12/T13). Covered.
- **Deviation from spec (documented):** the spec's "deterministic overlap re-import" is implemented as the stricter, safer **append-only continuation** (only hours strictly after the baseline are added; ACTUAL-only; future/in-progress hour skipped). This more directly prevents the reported spikes/negatives/resets; correcting already-imported past hours is explicitly out of scope for v1.
- **Type consistency:** `Interval`, `NightWindow`, `Baseline`, `Rates` defined in `statistics.py` (T2/T3) and consumed unchanged in `api.py` (T5) and `coordinator.py` (T8). `MeridianAuth`/`MeridianApi` signatures match across tasks.
- **Live-data gates:** cost-field extraction and OTP response shapes are verified at T6 Step 3 before any HA write; statistic-ID/unit continuity verified at T7 Step 3; end-to-end continuity at T12 Step 4.
