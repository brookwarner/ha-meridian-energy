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


def test_build_cost_continues_from_cost_baseline():
    base = datetime(2026, 6, 1, 0, tzinfo=timezone.utc)
    ivs = [_uiv(1, 10, kwh=2.0, cost=0.25), _uiv(2, 11, kwh=2.0, cost=0.25)]
    baselines = {
        const.STAT_DAY: Baseline(100.0, base),
        const.STAT_DAY_COST: Baseline(10.0, base),
    }
    out = build_statistics(ivs, W, None, baselines)
    cost_sums = [p["sum"] for p in out[const.STAT_DAY_COST]]
    assert cost_sums == [10.25, 10.50]  # continues from cost baseline 10.0, not 0

def test_build_cost_can_decrease_for_credits():
    out = build_statistics([_uiv(1, 10, kwh=1.0, cost=-0.40)], W, None, {})
    assert out[const.STAT_DAY_COST][0]["sum"] == -0.40  # credits allowed, no monotonic guard on cost

def test_build_negative_energy_skip_also_skips_cost():
    ivs = [_uiv(1, 10, kwh=-4.0), _uiv(2, 11, kwh=2.0)]
    out = build_statistics(ivs, W, None, {})
    assert len(out[const.STAT_DAY]) == 1
    assert len(out[const.STAT_DAY_COST]) == 1  # skipped-energy hour contributes no cost point
