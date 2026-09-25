from __future__ import annotations

from typing import Any


def poi(
    poi_id: str,
    name: str,
    *,
    address: str | None = "上海市测试路 1 号",
    location: str | None = "121.473700,31.230400",
    poi_type: str = "餐饮服务",
    typecode: str = "050000",
    distance: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": poi_id,
        "name": name,
        "address": address,
        "location": location,
        "pname": "上海市",
        "cityname": "上海市",
        "adname": "黄浦区",
        "adcode": "310101",
        "type": poi_type,
        "typecode": typecode,
    }
    if distance is not None:
        item["distance"] = distance
    return item


def success(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "1",
        "info": "OK",
        "infocode": "10000",
        "count": str(len(items)),
        "pois": items,
    }


def transit_success(durations: list[int]) -> dict[str, Any]:
    return {
        "status": "1",
        "info": "OK",
        "infocode": "10000",
        "count": str(len(durations)),
        "route": {
            "origin": "121.400000,31.200000",
            "destination": "121.500000,31.250000",
            "transits": [
                {
                    "cost": {"duration": str(duration)},
                    "segments": [
                        {
                            "walking": {
                                "steps": [{"instruction": "步行至测试站"}]
                            },
                            "bus": {
                                "buslines": [
                                    {
                                        "name": "测试地铁线",
                                        "departure_stop": {"name": "测试起点站"},
                                        "arrival_stop": {"name": "测试终点站"},
                                    }
                                ]
                            },
                        }
                    ],
                }
                for duration in durations
            ],
        },
    }
