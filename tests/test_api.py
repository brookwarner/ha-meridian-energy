from datetime import date

import aiohttp
from aioresponses import aioresponses

import pytest

from meridian_energy import const
from meridian_energy.api import MeridianApi, MeridianApiError
from meridian_energy.auth import MeridianAuth, MeridianAuthError, MeridianConnectionError


class _StubAuth(MeridianAuth):
    def __init__(self):
        self._account_number = "A-TEST"  # bypass base init for tests

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


async def test_graphql_retries_once_on_401_then_succeeds():
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
            m.post(f"{const.GRAPHQL_URL}?opName=account", status=401, payload={})
            m.post(f"{const.GRAPHQL_URL}?opName=account", status=200, payload=payload)
            acc = await api.async_get_account()
    assert acc.account_number == "A-F53DF172"
    assert acc.property_id == "349524"


async def test_graphql_persistent_401_raises_auth_error():
    async with aiohttp.ClientSession() as session:
        api = MeridianApi(session, _StubAuth())
        with aioresponses() as m:
            m.post(f"{const.GRAPHQL_URL}?opName=account", status=401, payload={})
            m.post(f"{const.GRAPHQL_URL}?opName=account", status=401, payload={})
            with pytest.raises(MeridianAuthError):
                await api.async_get_account()


async def test_graphql_5xx_raises_connection_error():
    async with aiohttp.ClientSession() as session:
        api = MeridianApi(session, _StubAuth())
        with aioresponses() as m:
            m.post(f"{const.GRAPHQL_URL}?opName=account", status=500, payload={})
            with pytest.raises(MeridianConnectionError):
                await api.async_get_account()


async def test_graphql_non_json_raises_connection_error():
    async with aiohttp.ClientSession() as session:
        api = MeridianApi(session, _StubAuth())
        with aioresponses() as m:
            m.post(f"{const.GRAPHQL_URL}?opName=account", status=200, body="not json")
            with pytest.raises(MeridianConnectionError):
                await api.async_get_account()


async def test_map_node_skips_future_hour():
    edges = [
        _edge("2.5", "2099-01-01T10:00:00+13:00", "2099-01-01T11:00:00+13:00")
    ]
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
    assert intervals == []
