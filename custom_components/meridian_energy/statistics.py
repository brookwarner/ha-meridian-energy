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
