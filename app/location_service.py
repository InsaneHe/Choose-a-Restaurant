"""Orchestration for safe automatic restaurant location resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.map_provider import MapProvider, MapProviderError, choose_auto_candidate
from app.storage import (
    DEFAULT_DATA_PATH,
    ManualLocationProtectedError,
    RestaurantConflictError,
    RestaurantNotFoundError,
    load_restaurant_snapshot,
    load_restaurants,
    set_restaurant_location,
)


def resolve_restaurant_location(
    restaurant_id: int,
    provider: MapProvider,
    path: Path | str = DEFAULT_DATA_PATH,
) -> dict[str, Any]:
    snapshot = load_restaurant_snapshot(path)
    restaurants = snapshot.restaurants
    restaurant = next(
        (item for item in restaurants if item["id"] == restaurant_id), None
    )
    if restaurant is None:
        raise RestaurantNotFoundError(f"未找到餐厅 id {restaurant_id}")

    if restaurant["location_status"] == "manual_confirmed":
        return {
            "restaurant_id": restaurant_id,
            "name": restaurant["name"],
            "status": "protected_manual",
            "candidates": [],
        }
    if restaurant["location_status"] == "auto_resolved":
        return {
            "restaurant_id": restaurant_id,
            "name": restaurant["name"],
            "status": "already_resolved",
            "candidates": [],
        }

    candidates = provider.search_places(restaurant["name"])
    auto_candidate = choose_auto_candidate(restaurant["name"], candidates)
    if auto_candidate is None:
        return {
            "restaurant_id": restaurant_id,
            "name": restaurant["name"],
            "status": "needs_confirmation" if candidates else "no_candidates",
            "candidates": [candidate.to_dict() for candidate in candidates],
        }

    try:
        saved = set_restaurant_location(
            restaurant_id,
            address=auto_candidate.address or "",
            longitude=float(auto_candidate.longitude),
            latitude=float(auto_candidate.latitude),
            amap_poi_id=auto_candidate.poi_id,
            location_status="auto_resolved",
            path=path,
            expected_version=snapshot.version,
        )
    except ManualLocationProtectedError:
        return {
            "restaurant_id": restaurant_id,
            "name": restaurant["name"],
            "status": "protected_manual",
            "candidates": [],
        }
    except RestaurantConflictError as exc:
        return {
            "restaurant_id": restaurant_id,
            "name": restaurant["name"],
            "status": "conflict",
            "error": str(exc),
            "candidates": [],
        }

    return {
        "restaurant_id": restaurant_id,
        "name": restaurant["name"],
        "status": "auto_resolved",
        "restaurant": saved,
        "candidates": [auto_candidate.to_dict()],
    }


def resolve_pending_restaurants(
    provider: MapProvider, path: Path | str = DEFAULT_DATA_PATH
) -> list[dict[str, Any]]:
    restaurant_ids = [restaurant["id"] for restaurant in load_restaurants(path)]
    results: list[dict[str, Any]] = []
    consecutive_provider_errors = 0
    for restaurant_id in restaurant_ids:
        if consecutive_provider_errors >= 3:
            current = next(
                (
                    item
                    for item in load_restaurants(path)
                    if item["id"] == restaurant_id
                ),
                None,
            )
            results.append(
                {
                    "restaurant_id": restaurant_id,
                    "name": current["name"] if current else "",
                    "status": "skipped_service_failures",
                    "error": "连续高德请求失败，后续自动定位已停止以控制调用量",
                    "candidates": [],
                }
            )
            continue
        try:
            result = resolve_restaurant_location(restaurant_id, provider, path)
            results.append(result)
            consecutive_provider_errors = 0
        except MapProviderError as exc:
            consecutive_provider_errors += 1
            current = next(
                (
                    item
                    for item in load_restaurants(path)
                    if item["id"] == restaurant_id
                ),
                None,
            )
            results.append(
                {
                    "restaurant_id": restaurant_id,
                    "name": current["name"] if current else "",
                    "status": "error",
                    "error": str(exc),
                    "candidates": [],
                }
            )
    return results
