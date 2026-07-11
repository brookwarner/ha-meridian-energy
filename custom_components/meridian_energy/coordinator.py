"""Coordinator: fetch measurements and import continuous statistics."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData

try:
    from homeassistant.components.recorder.models import StatisticMeanType

    _MEAN_METADATA = {"mean_type": StatisticMeanType.NONE}
except ImportError:  # HA older than the mean_type change
    _MEAN_METADATA = {"has_mean": False}
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
from .statistics import Baseline, NightWindow, Rates, build_statistics, fetch_window_hours

_LOGGER = logging.getLogger(__name__)
_UPDATE_INTERVAL = timedelta(hours=3)
_MIN_FETCH_HOURS = 168  # one week floor per run; append-only dedupe handles overlap
_MAX_FETCH_HOURS = 24 * 365  # cap backfill span for fresh installs / long gaps

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
        baselines = await self._async_read_baselines()
        try:
            if self._account is None:
                self._account = await self._api.async_get_account()
            account = self._account
            hours = fetch_window_hours(
                baselines, datetime.now(timezone.utc), _MIN_FETCH_HOURS, _MAX_FETCH_HOURS
            )
            cons = await self._api.async_get_recent(
                account.property_id, "CONSUMPTION", hours
            )
            gen = (
                await self._api.async_get_recent(
                    account.property_id, "GENERATION", hours
                )
                if account.has_solar
                else []
            )
        except MeridianAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (MeridianConnectionError, MeridianApiError) as err:
            raise UpdateFailed(str(err)) from err

        series = build_statistics(cons + gen, self._night_window(), self._rates(), baselines)

        totals: dict[str, float] = {}
        for sid, points in series.items():
            if not points:
                continue
            metadata = StatisticMetaData(
                has_sum=True,
                name=_STAT_NAMES[sid],
                source=const.DOMAIN,
                statistic_id=sid,
                unit_of_measurement=(
                    const.UNIT_ENERGY if sid in _ENERGY_IDS else const.UNIT_COST
                ),
                **_MEAN_METADATA,
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
                raw_start = row["start"]
                if isinstance(raw_start, (int, float)):
                    start = datetime.fromtimestamp(raw_start, tz=timezone.utc)
                elif raw_start.tzinfo is None:
                    start = raw_start.replace(tzinfo=timezone.utc)
                else:
                    start = raw_start.astimezone(timezone.utc)
                baselines[sid] = Baseline(last_sum=row["sum"] or 0.0, last_start_utc=start)
        return baselines
