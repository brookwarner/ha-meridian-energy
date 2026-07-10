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
            # Gate cost points on the ENERGY baseline: energy and cost are always
            # emitted together for the same hour below, so a cost series can
            # never outrun its paired energy series (a separate cost-baseline
            # check here would be redundant).
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
