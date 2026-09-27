import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

import app.storage as storage_module
from app.main import (
    GroupRandomRequest,
    GroupRankRequest,
    RestaurantSelectionStatusUpdate,
    create_app,
)
from app.map_provider import PublicTransitRoute
from app.ranking import (
    GroupRandomUnavailableError,
    GroupRankingState,
    perform_group_ranking,
    rank_restaurants,
)
from app.selection import EmptyRestaurantListError, choose_restaurant
from app.storage import (
    RestaurantConflictError,
    RestaurantDataError,
    load_restaurant_snapshot,
    load_restaurants,
    set_restaurant_selection_status,
    update_restaurant,
)


def restaurant(
    restaurant_id: int,
    name: str,
    *,
    selection_status: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": restaurant_id,
        "name": name,
        "type": "正餐",
        "detail": "测试菜系",
        "address": f"上海市{name}地址",
        "longitude": 121.47 + restaurant_id / 1000,
        "latitude": 31.23,
        "amap_poi_id": f"POI-{restaurant_id}",
        "dianping_url": None,
        "location_status": "manual_confirmed",
    }
    if selection_status is not None:
        record["selection_status"] = selection_status
    return record


def participants() -> list[dict[str, Any]]:
    return [
        {
            "participant_id": "p1",
            "name": "甲",
            "address": "上海市甲出发地",
            "longitude": 121.4,
            "latitude": 31.2,
            "amap_poi_id": "ORIGIN-1",
        },
        {
            "participant_id": "p2",
            "name": "乙",
            "address": "上海市乙出发地",
            "longitude": 121.42,
            "latitude": 31.21,
            "amap_poi_id": "ORIGIN-2",
        },
    ]


def route(seconds: int = 600) -> PublicTransitRoute:
    return PublicTransitRoute(seconds, "合成公交方案", ("测试线路",))


class SyntheticProvider:
    configured = True

    def best_public_transit_route(self, *args: object, **kwargs: object) -> PublicTransitRoute:
        return route()


class ArchivingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).parent / f".v2-01-{uuid4().hex}.json"
        self.addCleanup(self.path.unlink, missing_ok=True)

    def write_json(self, value: object) -> None:
        self.path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def test_v1_records_default_active_without_rewriting_file(self) -> None:
        self.write_json([restaurant(1, "V1 餐厅")])
        before = self.path.read_bytes()

        loaded = load_restaurants(self.path)

        self.assertEqual(loaded[0]["selection_status"], "active")
        self.assertEqual(self.path.read_bytes(), before)

    def test_archive_restore_is_idempotent_and_preserves_identity_and_location(self) -> None:
        original = restaurant(7, "人工确认餐厅")
        self.write_json([original])

        archived = set_restaurant_selection_status(7, "archived", self.path)
        archived_bytes = self.path.read_bytes()
        archived_again = set_restaurant_selection_status(7, "archived", self.path)

        self.assertEqual(archived_again, archived)
        self.assertEqual(self.path.read_bytes(), archived_bytes)
        self.assertEqual(
            {
                key: value
                for key, value in archived.items()
                if key not in {"selection_status", "tags"}
            },
            original,
        )

        edited = update_restaurant(7, {"detail": "归档中编辑"}, self.path)
        self.assertEqual(edited["selection_status"], "archived")
        self.assertEqual(edited["detail"], "归档中编辑")
        self.assertEqual(edited["amap_poi_id"], original["amap_poi_id"])
        self.assertEqual(edited["location_status"], "manual_confirmed")

        restored = set_restaurant_selection_status(7, "active", self.path)
        self.assertEqual(restored["selection_status"], "active")
        self.assertEqual(restored["id"], original["id"])
        self.assertEqual(restored["detail"], "归档中编辑")
        self.assertEqual(restored["address"], original["address"])
        self.assertEqual(restored["longitude"], original["longitude"])
        self.assertEqual(restored["latitude"], original["latitude"])
        self.assertEqual(restored["amap_poi_id"], original["amap_poi_id"])
        self.assertEqual(restored["location_status"], "manual_confirmed")

    def test_invalid_status_and_invalid_json_are_never_overwritten(self) -> None:
        self.write_json([restaurant(1, "有效餐厅")])
        valid_bytes = self.path.read_bytes()
        with self.assertRaisesRegex(RestaurantDataError, "selection_status"):
            set_restaurant_selection_status(1, "hidden", self.path)
        self.assertEqual(self.path.read_bytes(), valid_bytes)

        invalid_bytes = b'[{"broken": true]'
        self.path.write_bytes(invalid_bytes)
        with self.assertRaisesRegex(RestaurantDataError, "JSON"):
            set_restaurant_selection_status(1, "archived", self.path)
        self.assertEqual(self.path.read_bytes(), invalid_bytes)

    def test_manual_edit_conflict_preserves_manual_file(self) -> None:
        self.write_json([restaurant(1, "原餐厅")])
        original_save = storage_module.save_restaurants

        def concurrent_save(
            records: list[dict[str, Any]], expected_version: str, path: Path
        ) -> None:
            self.write_json(
                [restaurant(1, "原餐厅"), restaurant(9, "手工新增餐厅")]
            )
            original_save(records, expected_version, path)

        with patch.object(
            storage_module, "save_restaurants", side_effect=concurrent_save
        ):
            with self.assertRaisesRegex(RestaurantConflictError, "已被修改"):
                set_restaurant_selection_status(1, "archived", self.path)

        self.assertEqual(
            [item["id"] for item in load_restaurants(self.path)], [1, 9]
        )

    def test_direct_file_status_edit_is_visible_on_next_read(self) -> None:
        self.write_json([restaurant(1, "直接编辑餐厅", selection_status="active")])
        self.assertEqual(load_restaurants(self.path)[0]["selection_status"], "active")

        self.write_json(
            [restaurant(1, "直接编辑餐厅", selection_status="archived")]
        )
        self.assertEqual(
            load_restaurants(self.path)[0]["selection_status"], "archived"
        )

    def test_single_random_uses_only_active_and_all_archived_is_empty(self) -> None:
        items = [
            restaurant(1, "活跃餐厅"),
            restaurant(2, "档案餐厅", selection_status="archived"),
        ]
        result = choose_restaurant(items, lambda lower, upper: upper)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["restaurant"]["id"], 1)

        items[0]["selection_status"] = "archived"
        with self.assertRaisesRegex(EmptyRestaurantListError, "活跃餐厅名单为空"):
            choose_restaurant(items)

    def test_group_ranking_and_random_exclude_archived_then_restore(self) -> None:
        active = restaurant(1, "活跃餐厅", selection_status="active")
        archived = restaurant(2, "档案餐厅", selection_status="archived")
        calls: list[int] = []

        def lookup(person: dict[str, Any], place: dict[str, Any]) -> PublicTransitRoute:
            calls.append(place["id"])
            return route()

        first = rank_restaurants([active, archived], participants(), lookup)
        self.assertEqual([item["restaurant"]["id"] for item in first["ranked"]], [1])
        self.assertEqual(first["restaurant_count"], 1)
        self.assertEqual(calls, [1, 1])

        state = GroupRankingState()
        first["data_version"] = "v1"
        ranking_id = state.record(first)
        draw = state.draw(ranking_id or "", "v1", lambda lower, upper: upper)
        self.assertEqual(draw["restaurant"]["id"], 1)

        archived["selection_status"] = "active"
        calls.clear()
        restored = rank_restaurants([active, archived], participants(), lookup)
        self.assertEqual(
            [item["restaurant"]["id"] for item in restored["ranked"]], [1, 2]
        )
        self.assertEqual(calls, [1, 1, 2, 2])

    def test_all_archived_has_no_rank_or_random_eligibility(self) -> None:
        items = [restaurant(1, "档案餐厅", selection_status="archived")]
        result = rank_restaurants(
            items,
            participants(),
            lambda person, place: self.fail("归档餐厅不应请求路线"),
        )
        self.assertEqual(result["restaurant_count"], 0)
        self.assertEqual(result["ranked"], [])
        self.assertEqual(result["excluded"], [])

        result["data_version"] = "all-archived"
        state = GroupRankingState()
        self.assertIsNone(state.record(result))

    def test_group_ranking_does_not_auto_locate_archived_restaurants(self) -> None:
        active = restaurant(1, "活跃餐厅", selection_status="active")
        archived = restaurant(2, "待定位档案", selection_status="archived")
        archived.update(
            {
                "address": None,
                "longitude": None,
                "latitude": None,
                "amap_poi_id": None,
                "location_status": "pending_location",
            }
        )
        self.write_json([active, archived])

        with patch("app.ranking.resolve_pending_restaurants") as resolver:
            result = perform_group_ranking(
                participants(), SyntheticProvider(), self.path
            )

        resolver.assert_not_called()
        self.assertEqual(result["restaurant_count"], 1)
        self.assertEqual(
            [item["restaurant"]["id"] for item in result["ranked"]], [1]
        )

    def test_direct_archive_invalidates_existing_group_random(self) -> None:
        self.write_json([restaurant(1, "活跃餐厅", selection_status="active")])
        snapshot = load_restaurant_snapshot(self.path)
        result = rank_restaurants(
            snapshot.restaurants, participants(), lambda person, place: route()
        )
        result["data_version"] = snapshot.version
        state = GroupRankingState()
        ranking_id = state.record(result)
        self.assertIsNotNone(ranking_id)

        self.write_json(
            [restaurant(1, "活跃餐厅", selection_status="archived")]
        )
        with self.assertRaisesRegex(GroupRandomUnavailableError, "已失效"):
            state.draw(
                ranking_id or "",
                load_restaurant_snapshot(self.path).version,
                lambda lower, upper: lower,
            )

    def test_api_archive_restore_random_and_page_contract(self) -> None:
        self.write_json([restaurant(1, "API 餐厅")])
        application = create_app(self.path, randint=lambda lower, upper: lower)

        def endpoint(path: str, method: str):
            return next(
                route.endpoint
                for route in application.routes
                if getattr(route, "path", None) == path
                and method in getattr(route, "methods", set())
            )

        list_endpoint = endpoint("/api/restaurants", "GET")
        status_endpoint = endpoint(
            "/api/restaurants/{restaurant_id}/selection-status", "PATCH"
        )
        random_endpoint = endpoint("/api/random", "POST")
        rank_endpoint = endpoint("/api/group/rank", "POST")

        self.assertEqual(list_endpoint()[0]["selection_status"], "active")

        archived = status_endpoint(
            1, RestaurantSelectionStatusUpdate(selection_status="archived")
        )
        self.assertEqual(archived["selection_status"], "archived")
        with self.assertRaisesRegex(HTTPException, "活跃餐厅名单为空"):
            random_endpoint()
        with self.assertRaisesRegex(HTTPException, "活跃餐厅名单为空"):
            rank_endpoint(GroupRankRequest(participants=participants()))

        before_invalid = self.path.read_bytes()
        with self.assertRaises(ValidationError):
            RestaurantSelectionStatusUpdate.model_validate(
                {"selection_status": "hidden"}
            )
        self.assertEqual(self.path.read_bytes(), before_invalid)

        restored = status_endpoint(
            1, RestaurantSelectionStatusUpdate(selection_status="active")
        )
        self.assertEqual(restored["selection_status"], "active")
        self.assertEqual(random_endpoint()["restaurant"]["id"], 1)

        page = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="archived-restaurants"', page)
        self.assertIn("餐厅档案", page)

    def test_api_archive_invalidates_group_random_until_reranked(self) -> None:
        self.write_json(
            [restaurant(1, "排名餐厅", selection_status="active")]
        )
        application = create_app(
            self.path,
            randint=lambda lower, upper: lower,
            map_provider=SyntheticProvider(),
        )

        def endpoint(path: str, method: str):
            return next(
                route.endpoint
                for route in application.routes
                if getattr(route, "path", None) == path
                and method in getattr(route, "methods", set())
            )

        ranked = endpoint("/api/group/rank", "POST")(
            GroupRankRequest(participants=participants())
        )
        ranking_id = ranked["ranking_id"]
        self.assertIsNotNone(ranking_id)

        endpoint("/api/restaurants/{restaurant_id}/selection-status", "PATCH")(
            1, RestaurantSelectionStatusUpdate(selection_status="archived")
        )
        with self.assertRaisesRegex(HTTPException, "没有最近一次"):
            endpoint("/api/group/random", "POST")(
                GroupRandomRequest(ranking_id=ranking_id)
            )


if __name__ == "__main__":
    unittest.main()
