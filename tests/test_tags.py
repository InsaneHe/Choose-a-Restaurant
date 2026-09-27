import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import app.storage as storage_module
from app.main import RestaurantCreate, RestaurantUpdate, create_app
from app.map_provider import PublicTransitRoute
from app.ranking import GroupRandomUnavailableError, GroupRankingState, rank_restaurants
from app.selection import choose_restaurant
from app.storage import (
    RestaurantConflictError,
    RestaurantDataError,
    create_restaurant,
    load_restaurant_snapshot,
    load_restaurants,
    update_restaurant,
)


def restaurant(
    restaurant_id: int,
    name: str = "标签测试餐厅",
    *,
    selection_status: str = "active",
    tags: list[str] | None = None,
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
        "selection_status": selection_status,
    }
    if tags is not None:
        record["tags"] = tags
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


def route() -> PublicTransitRoute:
    return PublicTransitRoute(600, "合成公交方案", ("测试线路",))


class TagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).parent / f".v2-02-{uuid4().hex}.json"
        self.addCleanup(self.path.unlink, missing_ok=True)

    def write_json(self, value: object) -> None:
        self.path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def test_old_record_defaults_to_empty_tags_without_rewriting(self) -> None:
        self.write_json([restaurant(1)])
        before = self.path.read_bytes()

        loaded = load_restaurants(self.path)

        self.assertEqual(loaded[0]["tags"], [])
        self.assertEqual(self.path.read_bytes(), before)

    def test_create_normalizes_unicode_tags_without_inferring_from_name(self) -> None:
        self.write_json([])
        created = create_restaurant(
            "门店(总店)",
            "正餐",
            "测试",
            path=self.path,
            tags=[" 总店 ", "總店", "Branch", "branch", "总店"],
        )
        inferred = create_restaurant("另一家(分店)", "正餐", "测试", path=self.path)

        self.assertEqual(created["tags"], ["总店", "總店", "Branch", "branch"])
        self.assertEqual(inferred["tags"], [])
        self.assertEqual(
            load_restaurants(self.path)[0]["tags"],
            ["总店", "總店", "Branch", "branch"],
        )

    def test_update_and_explicit_empty_array_clear_tags(self) -> None:
        self.write_json([restaurant(1, tags=["旧标签"])])

        updated = update_restaurant(
            1, {"tags": [" 新标签 ", "外文", "新标签"]}, self.path
        )
        self.assertEqual(updated["tags"], ["新标签", "外文"])

        cleared = update_restaurant(1, {"tags": []}, self.path)
        self.assertEqual(cleared["tags"], [])
        self.assertEqual(load_restaurants(self.path)[0]["tags"], [])

    def test_archived_tags_are_editable_and_preserve_all_other_fields(self) -> None:
        original = restaurant(
            7,
            "档案餐厅",
            selection_status="archived",
            tags=["旧标签"],
        )
        self.write_json([original])

        updated = update_restaurant(7, {"tags": ["總店", "Café"]}, self.path)

        self.assertEqual(updated["tags"], ["總店", "Café"])
        for field, value in original.items():
            if field != "tags":
                self.assertEqual(updated[field], value)

    def test_invalid_tag_shapes_never_modify_the_file(self) -> None:
        invalid_values = ["不是数组", ["有效", 7], ["   "]]
        for invalid in invalid_values:
            with self.subTest(value=invalid):
                record = restaurant(1)
                record["tags"] = invalid
                self.write_json([record])
                before = self.path.read_bytes()
                with self.assertRaisesRegex(RestaurantDataError, "tags|标签"):
                    load_restaurants(self.path)
                self.assertEqual(self.path.read_bytes(), before)

        self.write_json([restaurant(1, tags=["原标签"])])
        before_update = self.path.read_bytes()
        with self.assertRaisesRegex(RestaurantDataError, "tags"):
            update_restaurant(1, {"tags": "错误类型"}, self.path)
        self.assertEqual(self.path.read_bytes(), before_update)

    def test_manual_tag_edit_is_visible_on_next_read(self) -> None:
        self.write_json([restaurant(1, tags=["程序标签"])])
        self.assertEqual(load_restaurants(self.path)[0]["tags"], ["程序标签"])

        self.write_json([restaurant(1, tags=[" 手工標籤 ", "Manual"])])
        self.assertEqual(
            load_restaurants(self.path)[0]["tags"], ["手工標籤", "Manual"]
        )

    def test_tag_write_conflict_preserves_manual_change(self) -> None:
        self.write_json([restaurant(1, tags=["原标签"])])
        original_save = storage_module.save_restaurants

        def concurrent_save(
            records: list[dict[str, Any]], expected_version: str, path: Path
        ) -> None:
            self.write_json([restaurant(1, tags=["手工抢先标签"])])
            original_save(records, expected_version, path)

        with patch.object(
            storage_module, "save_restaurants", side_effect=concurrent_save
        ):
            with self.assertRaisesRegex(RestaurantConflictError, "已被修改"):
                update_restaurant(1, {"tags": ["程序候选标签"]}, self.path)

        self.assertEqual(
            load_restaurants(self.path)[0]["tags"], ["手工抢先标签"]
        )

    def test_tag_change_keeps_eligibility_and_location_but_invalidates_old_result(self) -> None:
        active = restaurant(1, "活跃餐厅", tags=["原标签"])
        archived = restaurant(
            2,
            "档案餐厅",
            selection_status="archived",
            tags=["档案"],
        )
        self.write_json([active, archived])
        before = load_restaurant_snapshot(self.path)

        first = rank_restaurants(before.restaurants, participants(), lambda p, r: route())
        first["data_version"] = before.version
        state = GroupRankingState()
        ranking_id = state.record(first)
        self.assertIsNotNone(ranking_id)
        self.assertEqual(
            choose_restaurant(before.restaurants, lambda low, high: high)["restaurant"]["id"],
            1,
        )

        updated = update_restaurant(1, {"tags": ["新标签"]}, self.path)
        self.assertEqual(updated["selection_status"], "active")
        self.assertEqual(updated["location_status"], "manual_confirmed")
        self.assertEqual(updated["address"], active["address"])
        self.assertEqual(updated["longitude"], active["longitude"])
        self.assertEqual(updated["latitude"], active["latitude"])
        self.assertEqual(updated["amap_poi_id"], active["amap_poi_id"])

        after = load_restaurant_snapshot(self.path)
        with self.assertRaisesRegex(GroupRandomUnavailableError, "已失效"):
            state.draw(ranking_id or "", after.version)
        reranked = rank_restaurants(
            after.restaurants, participants(), lambda p, r: route()
        )
        self.assertEqual(
            [item["restaurant"]["id"] for item in reranked["ranked"]], [1]
        )

    def test_existing_crud_api_supports_create_update_and_clear(self) -> None:
        self.write_json([])
        application = create_app(self.path)

        def endpoint(path: str, method: str):
            return next(
                route.endpoint
                for route in application.routes
                if getattr(route, "path", None) == path
                and method in getattr(route, "methods", set())
            )

        created = endpoint("/api/restaurants", "POST")(
            RestaurantCreate(
                name="API 标签餐厅",
                type="正餐",
                detail="测试",
                tags=[" 总店 ", "總店", "总店"],
            )
        )
        self.assertEqual(created["tags"], ["总店", "總店"])

        edited = endpoint("/api/restaurants/{restaurant_id}", "PATCH")(
            created["id"], RestaurantUpdate(tags=["Branch", "分店"])
        )
        self.assertEqual(edited["tags"], ["Branch", "分店"])

        cleared = endpoint("/api/restaurants/{restaurant_id}", "PATCH")(
            created["id"], RestaurantUpdate(tags=[])
        )
        self.assertEqual(cleared["tags"], [])

        page = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="tag-editor"', page)
        self.assertIn("chip.textContent = tag", script)


if __name__ == "__main__":
    unittest.main()
