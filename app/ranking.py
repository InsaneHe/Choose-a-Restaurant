"""W04 group public-transit ranking and ephemeral random eligibility."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.location_service import resolve_pending_restaurants
from app.map_provider import MapProvider, MapProviderError, PublicTransitRoute
from app.selection import choose_restaurant
from app.storage import DEFAULT_DATA_PATH, load_restaurant_snapshot


SHANGHAI_LONGITUDE_RANGE = (120.8, 122.3)
SHANGHAI_LATITUDE_RANGE = (30.6, 31.9)
MAX_CONSECUTIVE_ROUTE_ERRORS = 3


class GroupRankingError(ValueError):
    """Raised for invalid participant or ranking input."""


class GroupRandomUnavailableError(ValueError):
    """Raised when there is no current successful group ranking."""


RouteLookup = Callable[[dict[str, Any], dict[str, Any]], PublicTransitRoute | None]


def _restaurant_view(restaurant: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": restaurant["id"],
        "name": restaurant["name"],
        "type": restaurant["type"],
        "address": restaurant["address"],
        "longitude": restaurant["longitude"],
        "latitude": restaurant["latitude"],
        "amap_poi_id": restaurant["amap_poi_id"],
        "location_status": restaurant["location_status"],
    }


def validate_participants(
    participants: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(participants) < 2:
        raise GroupRankingError("多人排名至少需要两名参与者")

    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, participant in enumerate(participants, start=1):
        participant_id = str(participant.get("participant_id", "")).strip()
        name = str(participant.get("name", "")).strip()
        address = str(participant.get("address", "")).strip()
        longitude = participant.get("longitude")
        latitude = participant.get("latitude")
        poi_id_value = participant.get("amap_poi_id")
        poi_id = str(poi_id_value).strip() if poi_id_value else None

        if not participant_id or participant_id in seen_ids:
            raise GroupRankingError(f"第 {index} 名参与者标识为空或重复")
        seen_ids.add(participant_id)
        if not name:
            raise GroupRankingError(f"第 {index} 名参与者缺少名称")
        if not address:
            raise GroupRankingError(f"第 {index} 名参与者尚未确认出发地址")
        if (
            isinstance(longitude, bool)
            or isinstance(latitude, bool)
            or not isinstance(longitude, (int, float))
            or not isinstance(latitude, (int, float))
        ):
            raise GroupRankingError(f"第 {index} 名参与者尚未确认有效坐标")
        if not SHANGHAI_LONGITUDE_RANGE[0] <= longitude <= SHANGHAI_LONGITUDE_RANGE[1]:
            raise GroupRankingError(f"第 {index} 名参与者经度不在上海范围")
        if not SHANGHAI_LATITUDE_RANGE[0] <= latitude <= SHANGHAI_LATITUDE_RANGE[1]:
            raise GroupRankingError(f"第 {index} 名参与者纬度不在上海范围")

        validated.append(
            {
                "participant_id": participant_id,
                "name": name,
                "address": address,
                "longitude": float(longitude),
                "latitude": float(latitude),
                "amap_poi_id": poi_id,
            }
        )
    return validated


def rank_restaurants(
    restaurants: Sequence[dict[str, Any]],
    participants: Sequence[dict[str, Any]],
    route_lookup: RouteLookup,
) -> dict[str, Any]:
    """Rank every reliably located restaurant; never substitute missing routes."""

    checked_participants = validate_participants(participants)
    ranked: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    route_request_count = 0
    service_error_count = 0
    consecutive_service_errors = 0
    route_checks_stopped = False

    for restaurant in restaurants:
        restaurant_view = _restaurant_view(restaurant)
        if (
            restaurant["location_status"] not in {"auto_resolved", "manual_confirmed"}
            or restaurant["longitude"] is None
            or restaurant["latitude"] is None
        ):
            excluded.append(
                {
                    "restaurant": restaurant_view,
                    "code": "location_unconfirmed",
                    "reason": "门店位置尚未确认",
                }
            )
            continue

        if route_checks_stopped:
            excluded.append(
                {
                    "restaurant": restaurant_view,
                    "code": "route_checks_stopped",
                    "reason": "连续路线服务失败，后续请求已停止以控制调用量",
                }
            )
            continue

        participant_routes: list[dict[str, Any]] = []
        failure: dict[str, Any] | None = None
        for participant in checked_participants:
            route_request_count += 1
            try:
                route = route_lookup(participant, restaurant)
                consecutive_service_errors = 0
            except MapProviderError as exc:
                service_error_count += 1
                consecutive_service_errors += 1
                failure = {
                    "restaurant": restaurant_view,
                    "code": "route_service_error",
                    "reason": f"{participant['name']} 的公交请求失败：{exc}",
                    "participant_id": participant["participant_id"],
                }
                if consecutive_service_errors >= MAX_CONSECUTIVE_ROUTE_ERRORS:
                    route_checks_stopped = True
                break

            if route is None:
                failure = {
                    "restaurant": restaurant_view,
                    "code": "no_route",
                    "reason": f"{participant['name']} 没有有效公共交通方案",
                    "participant_id": participant["participant_id"],
                }
                break

            participant_routes.append(
                {
                    "participant_id": participant["participant_id"],
                    "participant_name": participant["name"],
                    "origin_address": participant["address"],
                    **route.to_dict(),
                }
            )

        if failure is not None:
            excluded.append(failure)
            continue

        durations = [route["duration_seconds"] for route in participant_routes]
        ranked.append(
            {
                "restaurant": restaurant_view,
                "total_seconds": sum(durations),
                "slowest_seconds": max(durations),
                "routes": participant_routes,
            }
        )

    ranked.sort(
        key=lambda item: (
            item["total_seconds"],
            item["slowest_seconds"],
            item["restaurant"]["id"],
        )
    )
    for position, item in enumerate(ranked, start=1):
        item["rank"] = position

    coverage_complete = service_error_count == 0 and not route_checks_stopped
    return {
        "participants": checked_participants,
        "ranked": ranked,
        "excluded": excluded,
        "coverage_complete": coverage_complete,
        "route_request_count": route_request_count,
        "service_error_count": service_error_count,
        "restaurant_count": len(restaurants),
        "located_count": sum(
            1
            for item in restaurants
            if item["location_status"] in {"auto_resolved", "manual_confirmed"}
            and item["longitude"] is not None
            and item["latitude"] is not None
        ),
    }


def perform_group_ranking(
    participants: Sequence[dict[str, Any]],
    provider: MapProvider,
    path: Path | str = DEFAULT_DATA_PATH,
) -> dict[str, Any]:
    """Attempt pending locations, then rank all currently reliable locations."""

    checked_participants = validate_participants(participants)
    before = load_restaurant_snapshot(path)
    location_results: list[dict[str, Any]] = []
    if any(item["location_status"] == "pending_location" for item in before.restaurants):
        location_results = resolve_pending_restaurants(provider, path)

    after = load_restaurant_snapshot(path)

    def route_lookup(
        participant: dict[str, Any], restaurant: dict[str, Any]
    ) -> PublicTransitRoute | None:
        return provider.best_public_transit_route(
            participant["longitude"],
            participant["latitude"],
            restaurant["longitude"],
            restaurant["latitude"],
            origin_poi_id=participant["amap_poi_id"],
            destination_poi_id=restaurant["amap_poi_id"],
        )

    result = rank_restaurants(after.restaurants, checked_participants, route_lookup)
    location_failures = [
        item
        for item in location_results
        if item["status"] in {"error", "conflict", "skipped_service_failures"}
    ]
    if location_failures:
        result["coverage_complete"] = False
    result["data_version"] = after.version
    result["location_resolution"] = [
        {
            "restaurant_id": item["restaurant_id"],
            "name": item["name"],
            "status": item["status"],
            **({"error": item["error"]} if item.get("error") else {}),
        }
        for item in location_results
    ]
    return result


class GroupRankingState:
    """Keep only the latest local-session ranking eligibility in memory."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, Any] | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._latest = None

    def record(self, result: dict[str, Any]) -> str | None:
        with self._lock:
            if not result["coverage_complete"] or not result["ranked"]:
                self._latest = None
                return None
            ranking_id = uuid4().hex
            self._latest = {
                "ranking_id": ranking_id,
                "data_version": result["data_version"],
                "eligible": [item["restaurant"] for item in result["ranked"]],
            }
            return ranking_id

    def draw(
        self,
        ranking_id: str,
        current_data_version: str,
        randint: Callable[[int, int], int] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            latest = self._latest
            if latest is None or latest["ranking_id"] != ranking_id:
                raise GroupRandomUnavailableError(
                    "没有最近一次成功且未失效的完整排名，无法多人随机"
                )
            if latest["data_version"] != current_data_version:
                self._latest = None
                raise GroupRandomUnavailableError(
                    "餐厅数据已变化，旧排名已失效，请重新排名"
                )
            return choose_restaurant(latest["eligible"], randint)
