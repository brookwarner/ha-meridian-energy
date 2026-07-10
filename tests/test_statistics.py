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
