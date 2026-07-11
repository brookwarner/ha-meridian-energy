"""Meridian Energy GraphQL API client (new Kraken platform)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp

from . import const
from .auth import MeridianAuth, MeridianAuthError, MeridianConnectionError
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
query measurements($accountNumber: String!, $propertyId: ID!, $before: String, $last: Int, $endOn: Date, $readingFrequencyType: ReadingFrequencyType!, $readingDirectionType: ReadingDirectionType, $readingQualityType: ReadingQualityType) {
  account(accountNumber: $accountNumber) {
    id
    property(id: $propertyId) {
      id
      measurements(before: $before, last: $last, endOn: $endOn, timezone: "Pacific/Auckland", utilityFilters: [{electricityFilters: {readingDirection: $readingDirectionType, readingQuality: $readingQualityType, readingFrequencyType: $readingFrequencyType}}]) {
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
                    if resp.status == 401:
                        if attempt == 0:
                            self._auth.invalidate_token()  # force refresh, retry once
                            continue
                        raise MeridianAuthError("Unauthorized after token refresh")
                    if resp.status >= 500:
                        raise MeridianConnectionError(f"GraphQL server error {resp.status}")
                    try:
                        data = await resp.json(content_type=None)
                    except ValueError as err:
                        raise MeridianConnectionError(
                            f"Non-JSON GraphQL response: {err}"
                        ) from err
            except aiohttp.ClientError as err:
                raise MeridianConnectionError(str(err)) from err
            if data.get("errors"):
                raise MeridianApiError(str(data["errors"]))
            return data["data"]
        raise MeridianAuthError("Unauthorized after token refresh")

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
        before: str | None = None,
    ) -> tuple[list[Interval], str | None]:
        """Fetch one page of hourly measurements; return (intervals, prev_cursor).

        prev_cursor drives BACKWARD pagination: pass it as `before` on the
        next call to fetch the page of intervals immediately preceding this
        one (measurements are returned ordered ascending, most recent N
        ending at `end_on`).
        """
        variables = {
            "accountNumber": self._auth.account_number,
            "propertyId": property_id,
            "before": before,
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
        next_cursor = page.get("startCursor") if page.get("hasPreviousPage") else None
        return intervals, next_cursor

    async def async_get_recent(
        self, property_id: str, direction: str, hours: int
    ) -> list[Interval]:
        """Paginate measurements covering roughly the last `hours` hours."""
        end_on = datetime.now(_TZ).date()
        collected: list[Interval] = []
        before: str | None = None
        remaining = hours
        while remaining > 0:
            page_size = min(remaining, 168)
            intervals, before = await self.async_get_measurements(
                property_id, direction, end_on, page_size, before
            )
            collected.extend(intervals)
            remaining -= page_size
            if before is None:
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
        """Return this interval's usage-based cost in NZD, or None.

        Meridian returns estimatedAmount in CENTS. Each interval carries a
        STANDING_CHARGE_COST (a flat daily fee, constant per hour) plus a
        usage-based charge (CONSUMPTION_COST, or a generation credit for
        export). The per-kWh cost statistic should reflect the usage-based
        charge only, so the flat standing charge is excluded. Cents -> NZD.
        """
        stats = (node.get("metaData") or {}).get("statistics") or []
        total = None
        for entry in stats:
            if entry.get("type") == "STANDING_CHARGE_COST":
                continue
            incl = entry.get("costInclTax") or {}
            amount = incl.get("estimatedAmount")
            if amount is not None:
                total = (total or 0.0) + float(amount)
        return None if total is None else total / 100.0
