"""Injectable synthetic provider for the W04 browser smoke test."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.map_provider import MapProvider, TEXT_SEARCH_URL, TRANSIT_ROUTE_URL
from tests.fixtures.amap_responses import poi, success, transit_success


def _transport(
    endpoint: str, parameters: Mapping[str, str], timeout: float
) -> Mapping[str, Any]:
    if endpoint == TEXT_SEARCH_URL:
        query = parameters.get("keywords", "")
        if "甲地" in query:
            return success(
                [poi("ORIGIN-A", "合成甲地", address="上海市合成甲地", location="121.400000,31.200000")]
            )
        if "乙地" in query:
            return success(
                [poi("ORIGIN-B", "合成乙地", address="上海市合成乙地", location="121.410000,31.210000")]
            )
        if "合成餐厅甲" in query:
            return success(
                [poi("DEST-A2", "合成餐厅甲", address="上海市更正后合成地址", location="121.520000,31.260000")]
            )
        return success([])

    if endpoint == TRANSIT_ROUTE_URL:
        origin = parameters["origin"]
        destination = parameters["destination"]
        durations = {
            ("121.400000,31.200000", "121.500000,31.250000"): [1500, 1200],
            ("121.410000,31.210000", "121.500000,31.250000"): [2600, 2400],
            ("121.400000,31.200000", "121.510000,31.250000"): [1900, 1800],
            ("121.410000,31.210000", "121.510000,31.250000"): [2200, 2100],
            ("121.400000,31.200000", "121.520000,31.260000"): [1000, 900],
            ("121.410000,31.210000", "121.520000,31.260000"): [1300, 1200],
        }
        return transit_success(durations[(origin, destination)])

    raise AssertionError(f"unexpected synthetic endpoint: {endpoint}")


def build_smoke_provider() -> MapProvider:
    return MapProvider("synthetic-test-key", transport=_transport)
