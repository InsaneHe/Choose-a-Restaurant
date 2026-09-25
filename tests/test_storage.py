import json
import unittest
from pathlib import Path
from uuid import uuid4

from app.storage import (
    ManualLocationProtectedError,
    RestaurantConflictError,
    RestaurantDataError,
    create_restaurant,
    delete_restaurant,
    load_restaurant_snapshot,
    load_restaurants,
    save_restaurants,
    set_restaurant_location,
    update_restaurant,
)


def restaurant(restaurant_id: int, name: str = "测试餐厅") -> dict[str, object]:
    return {
        "id": restaurant_id,
        "name": name,
        "type": "正餐",
        "detail": "测试菜系",
        "address": None,
        "longitude": None,
        "latitude": None,
        "amap_poi_id": None,
        "dianping_url": None,
        "location_status": "pending_location",
    }


class LoadRestaurantsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).parent / f".restaurants-{uuid4().hex}.json"
        self.addCleanup(self.path.unlink, missing_ok=True)

    def write_json(self, value: object) -> None:
        self.path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def test_valid_file_and_manual_edit_are_read_each_time(self) -> None:
        self.write_json([restaurant(1)])
        self.assertEqual([item["id"] for item in load_restaurants(self.path)], [1])

        self.write_json([restaurant(1), restaurant(2, "手工新增餐厅")])
        self.assertEqual([item["id"] for item in load_restaurants(self.path)], [1, 2])

    def test_invalid_json_is_reported_without_modifying_file(self) -> None:
        invalid_content = '[{"id": 1]'
        self.path.write_text(invalid_content, encoding="utf-8")

        with self.assertRaisesRegex(RestaurantDataError, "JSON 解析失败"):
            load_restaurants(self.path)

        self.assertEqual(self.path.read_text(encoding="utf-8"), invalid_content)

    def test_duplicate_id_is_reported_without_modifying_file(self) -> None:
        self.write_json([restaurant(1), restaurant(1, "重复编号")])
        original_content = self.path.read_bytes()

        with self.assertRaisesRegex(RestaurantDataError, "id 1 重复"):
            load_restaurants(self.path)

        self.assertEqual(self.path.read_bytes(), original_content)

    def test_create_update_delete_round_trip(self) -> None:
        self.write_json([restaurant(3, "原有餐厅")])

        created = create_restaurant(
            "鼎泰豐 Café", "正餐", "台菜", path=self.path
        )
        self.assertEqual(created["id"], 4)
        self.assertEqual(load_restaurants(self.path)[-1]["name"], "鼎泰豐 Café")

        updated = update_restaurant(
            4, {"name": "鼎泰豐 Café 徐家匯店", "detail": "小籠包"}, self.path
        )
        self.assertEqual(updated["detail"], "小籠包")
        self.assertEqual(load_restaurants(self.path)[-1]["name"], "鼎泰豐 Café 徐家匯店")

        deleted = delete_restaurant(4, self.path)
        self.assertEqual(deleted["id"], 4)
        self.assertEqual([item["id"] for item in load_restaurants(self.path)], [3])

    def test_manual_edit_is_preserved_by_the_next_operation(self) -> None:
        self.write_json([restaurant(1)])
        create_restaurant("程序新增", "正餐", "本帮菜", path=self.path)

        manually_edited = [*load_restaurants(self.path), restaurant(9, "手工新增")]
        self.write_json(manually_edited)
        update_restaurant(1, {"detail": "已更新菜系"}, self.path)

        reloaded = load_restaurants(self.path)
        self.assertEqual([item["id"] for item in reloaded], [1, 2, 9])
        self.assertEqual(reloaded[-1]["name"], "手工新增")

    def test_duplicate_names_receive_different_ids(self) -> None:
        self.write_json([restaurant(1, "同名分店")])
        created = create_restaurant("同名分店", "正餐", "粤菜", path=self.path)

        reloaded = load_restaurants(self.path)
        self.assertEqual([item["name"] for item in reloaded], ["同名分店", "同名分店"])
        self.assertEqual(created["id"], 2)

    def test_invalid_json_is_not_overwritten_by_create(self) -> None:
        invalid_content = b'[{"broken": true]'
        self.path.write_bytes(invalid_content)

        with self.assertRaisesRegex(RestaurantDataError, "JSON 解析失败"):
            create_restaurant("不应写入", "正餐", "测试", path=self.path)

        self.assertEqual(self.path.read_bytes(), invalid_content)

    def test_version_conflict_preserves_manual_change(self) -> None:
        self.write_json([restaurant(1)])
        snapshot = load_restaurant_snapshot(self.path)
        candidate = [*snapshot.restaurants, restaurant(2, "程序候选")]

        self.write_json([restaurant(1), restaurant(7, "手工抢先保存")])
        manual_content = self.path.read_bytes()
        with self.assertRaisesRegex(RestaurantConflictError, "已被修改"):
            save_restaurants(candidate, snapshot.version, self.path)

        self.assertEqual(self.path.read_bytes(), manual_content)
        self.assertEqual([item["id"] for item in load_restaurants(self.path)], [1, 7])

    def test_name_change_clears_stale_location(self) -> None:
        located = restaurant(1)
        located.update(
            {
                "address": "旧地址",
                "longitude": 121.4,
                "latitude": 31.2,
                "amap_poi_id": "OLD_POI",
                "location_status": "auto_resolved",
            }
        )
        self.write_json([located])

        updated = update_restaurant(1, {"name": "新名称"}, self.path)

        self.assertIsNone(updated["address"])
        self.assertIsNone(updated["longitude"])
        self.assertIsNone(updated["latitude"])
        self.assertIsNone(updated["amap_poi_id"])
        self.assertEqual(updated["location_status"], "pending_location")

    def test_address_or_poi_change_clears_other_stale_location_data(self) -> None:
        located = restaurant(1)
        located.update(
            {
                "address": "旧地址",
                "longitude": 121.4,
                "latitude": 31.2,
                "amap_poi_id": "OLD_POI",
                "location_status": "manual_confirmed",
            }
        )

        with self.subTest("address"):
            self.write_json([located])
            updated = update_restaurant(1, {"address": "新地址"}, self.path)
            self.assertEqual(updated["address"], "新地址")
            self.assertIsNone(updated["amap_poi_id"])
            self.assertIsNone(updated["longitude"])
            self.assertIsNone(updated["latitude"])
            self.assertEqual(updated["location_status"], "pending_location")

        with self.subTest("poi"):
            self.write_json([located])
            updated = update_restaurant(1, {"amap_poi_id": "NEW_POI"}, self.path)
            self.assertEqual(updated["amap_poi_id"], "NEW_POI")
            self.assertIsNone(updated["address"])
            self.assertIsNone(updated["longitude"])
            self.assertIsNone(updated["latitude"])
            self.assertEqual(updated["location_status"], "pending_location")

    def test_dianping_link_is_validated_without_fetching(self) -> None:
        self.write_json([restaurant(1)])
        valid_url = "https://m.dianping.com/shopshare/abc123"
        created = create_restaurant(
            "链接餐厅", "正餐", "测试", valid_url, self.path
        )
        self.assertEqual(created["dianping_url"], valid_url)
        valid_content = self.path.read_bytes()

        with self.assertRaisesRegex(RestaurantDataError, "HTTPS 商户链接"):
            update_restaurant(
                created["id"],
                {"dianping_url": "https://example.com/shop/abc123"},
                self.path,
            )

        self.assertEqual(self.path.read_bytes(), valid_content)

    def test_location_save_validates_and_protects_manual_confirmation(self) -> None:
        self.write_json([restaurant(1)])
        automatic = set_restaurant_location(
            1,
            address="上海市测试路 1 号",
            longitude=121.4737,
            latitude=31.2304,
            amap_poi_id="AUTO-1",
            location_status="auto_resolved",
            path=self.path,
        )
        self.assertEqual(automatic["location_status"], "auto_resolved")

        manual = set_restaurant_location(
            1,
            address="上海市人工确认路 2 号",
            longitude=121.48,
            latitude=31.22,
            amap_poi_id="MANUAL-2",
            location_status="manual_confirmed",
            path=self.path,
        )
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ManualLocationProtectedError, "不会覆盖"):
            set_restaurant_location(
                1,
                address="不应覆盖",
                longitude=121.5,
                latitude=31.3,
                amap_poi_id="AUTO-3",
                location_status="auto_resolved",
                path=self.path,
            )
        self.assertEqual(manual["address"], "上海市人工确认路 2 号")
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
