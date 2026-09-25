"""Injectable synthetic provider for the W05 browser acceptance pass."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.map_provider import (
    AROUND_SEARCH_URL,
    MapProvider,
    TEXT_SEARCH_URL,
    TRANSIT_ROUTE_URL,
)
from tests.fixtures.amap_responses import poi, success, transit_success


def _transport(
    endpoint: str, parameters: Mapping[str, str], timeout: float
) -> Mapping[str, Any]:
    del timeout
    if endpoint == TEXT_SEARCH_URL:
        query = parameters.get("keywords", "")
        if "types" not in parameters:
            if "甲地" in query:
                return success(
                    [
                        poi(
                            "ORIGIN-A",
                            "合成甲地",
                            address="上海市合成甲地",
                            location="121.400000,31.200000",
                        )
                    ]
                )
            if "乙地" in query:
                return success(
                    [
                        poi(
                            "ORIGIN-B",
                            "合成乙地",
                            address="上海市合成乙地",
                            location="121.410000,31.210000",
                        )
                    ]
                )
            return success([])

        normalized = query.casefold()
        if "鼎泰" in query or "din" in normalized:
            return success(
                [
                    poi(
                        "STORE-A",
                        "鼎泰豐 Café（合成一店）",
                        address="上海市合成路 1 号",
                        location="121.500000,31.250000",
                    ),
                    poi(
                        "STORE-B",
                        "鼎泰豐 Café（合成二店）",
                        address="上海市合成路 2 号",
                        location="121.520000,31.260000",
                    ),
                ]
            )
        return success([])

    if endpoint == AROUND_SEARCH_URL:
        return success(
            [
                poi(
                    "METRO-1",
                    "合成地铁站",
                    address="合成路",
                    location="121.501000,31.250000",
                    poi_type="交通设施服务;地铁站",
                    typecode="150500",
                    distance="96",
                ),
                poi(
                    "BUS-1",
                    "合成公交站",
                    address="合成路",
                    location="121.502000,31.250000",
                    poi_type="交通设施服务;公交车站",
                    typecode="150700",
                    distance="191",
                ),
            ]
        )

    if endpoint == TRANSIT_ROUTE_URL:
        origin = parameters["origin"]
        destination = parameters["destination"]
        durations = {
            ("121.400000,31.200000", "121.500000,31.250000"): [1500, 1200],
            ("121.410000,31.210000", "121.500000,31.250000"): [2600, 2400],
            ("121.400000,31.200000", "121.520000,31.260000"): [1000, 900],
            ("121.410000,31.210000", "121.520000,31.260000"): [1300, 1200],
        }
        return transit_success(durations[(origin, destination)])

    raise AssertionError(f"unexpected synthetic endpoint: {endpoint}")


def build_w05_provider() -> MapProvider:
    return MapProvider("synthetic-test-key", transport=_transport)
