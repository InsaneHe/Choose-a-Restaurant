import json
import unittest
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.location_service import resolve_pending_restaurants, resolve_restaurant_location
from app.map_provider import (
    AROUND_SEARCH_URL,
    MAX_QUERY_VARIANTS,
    TEXT_SEARCH_URL,
    MapProvider,
    MapProviderError,
    build_query_variants,
)
from app.storage import load_restaurants, set_restaurant_location
from tests.fixtures.amap_responses import poi, success


def restaurant(restaurant_id: int, name: str) -> dict[str, object]:
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


class RecordingTransport:
    def __init__(self, payload: dict[str, Any] | Exception) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(
        self, endpoint: str, parameters: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        self.calls.append((endpoint, dict(parameters), timeout))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class MapProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).parent / f".w03-{uuid4().hex}.json"
        self.addCleanup(self.path.unlink, missing_ok=True)

    def write_restaurants(self, items: list[dict[str, object]]) -> None:
        self.path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def test_traditional_foreign_and_mixed_query_variants_are_bounded(self) -> None:
        variants = build_query_variants("鼎泰豐 Din Tai Fung")

        self.assertEqual(variants[0], "鼎泰豐 Din Tai Fung")
        self.assertTrue(any("鼎泰丰" in value for value in variants))
        self.assertTrue(any("din tai fung" in value for value in variants))
        self.assertLessEqual(len(variants), MAX_QUERY_VARIANTS)

    def test_search_is_shanghai_limited_and_deduplicates_poi_ids(self) -> None:
        transport = RecordingTransport(success([poi("P-1", "鼎泰豐")]))
        provider = MapProvider("test-key", transport=transport)

        candidates = provider.search_places("鼎泰豐")

        self.assertEqual([candidate.poi_id for candidate in candidates], ["P-1"])
        self.assertTrue(transport.calls)
        for endpoint, parameters, timeout in transport.calls:
            self.assertEqual(endpoint, TEXT_SEARCH_URL)
            self.assertEqual(parameters["region"], "上海市")
            self.assertEqual(parameters["city_limit"], "true")
            self.assertEqual(parameters["key"], "test-key")
            self.assertEqual(timeout, 5.0)

    def test_unique_complete_exact_candidate_is_saved_automatically(self) -> None:
        self.write_restaurants([restaurant(1, "鼎泰豐")])
        provider = MapProvider(
            "test-key",
            transport=RecordingTransport(success([poi("P-1", "鼎泰豐")])),
        )

        result = resolve_restaurant_location(1, provider, self.path)
        saved = load_restaurants(self.path)[0]

        self.assertEqual(result["status"], "auto_resolved")
        self.assertEqual(saved["name"], "鼎泰豐")
        self.assertEqual(saved["location_status"], "auto_resolved")
        self.assertEqual(saved["amap_poi_id"], "P-1")

    def test_same_name_multiple_branches_never_auto_select(self) -> None:
        self.write_restaurants([restaurant(1, "同名餐厅")])
        branches = [
            poi("P-1", "同名餐厅", address="上海市测试路 1 号"),
            poi("P-2", "同名餐厅", address="上海市测试路 2 号"),
        ]
        provider = MapProvider(
            "test-key", transport=RecordingTransport(success(branches))
        )

        result = resolve_restaurant_location(1, provider, self.path)

        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(
            load_restaurants(self.path)[0]["location_status"], "pending_location"
        )

    def test_incomplete_or_fuzzy_unique_candidate_needs_confirmation(self) -> None:
        self.write_restaurants([restaurant(1, "原始店名")])
        provider = MapProvider(
            "test-key",
            transport=RecordingTransport(
                success([poi("P-1", "原始店名分店", address=None)])
            ),
        )

        result = resolve_restaurant_location(1, provider, self.path)

        self.assertEqual(result["status"], "needs_confirmation")
        self.assertIsNone(load_restaurants(self.path)[0]["address"])

    def test_manual_location_is_not_queried_or_overwritten(self) -> None:
        self.write_restaurants([restaurant(1, "人工餐厅")])
        set_restaurant_location(
            1,
            address="上海市人工路 8 号",
            longitude=121.4,
            latitude=31.2,
            amap_poi_id=None,
            location_status="manual_confirmed",
            path=self.path,
        )
        transport = RecordingTransport(success([poi("P-X", "人工餐厅")]))

        result = resolve_restaurant_location(
            1, MapProvider("test-key", transport=transport), self.path
        )

        self.assertEqual(result["status"], "protected_manual")
        self.assertEqual(transport.calls, [])
        self.assertEqual(load_restaurants(self.path)[0]["address"], "上海市人工路 8 号")

    def test_manual_file_change_during_search_returns_conflict(self) -> None:
        self.write_restaurants([restaurant(1, "搜索中的餐厅")])
        changed = False

        def change_file_during_search(
            endpoint: str, parameters: dict[str, str], timeout: float
        ) -> dict[str, Any]:
            nonlocal changed
            if not changed:
                changed = True
                set_restaurant_location(
                    1,
                    address="上海市用户抢先确认路 9 号",
                    longitude=121.41,
                    latitude=31.21,
                    amap_poi_id=None,
                    location_status="manual_confirmed",
                    path=self.path,
                )
            return success([poi("P-OLD", "搜索中的餐厅")])

        result = resolve_restaurant_location(
            1,
            MapProvider("test-key", transport=change_file_during_search),
            self.path,
        )

        saved = load_restaurants(self.path)[0]
        self.assertEqual(result["status"], "conflict")
        self.assertIn("已被修改", result["error"])
        self.assertEqual(saved["location_status"], "manual_confirmed")
        self.assertEqual(saved["address"], "上海市用户抢先确认路 9 号")

    def test_no_candidate_is_explicit(self) -> None:
        self.write_restaurants([restaurant(1, "不存在的店")])
        provider = MapProvider(
            "test-key", transport=RecordingTransport(success([]))
        )

        result = resolve_restaurant_location(1, provider, self.path)

        self.assertEqual(result["status"], "no_candidates")
        self.assertEqual(result["candidates"], [])

    def test_no_station_and_top_five_sorted_station_results(self) -> None:
        empty_provider = MapProvider(
            "test-key", transport=RecordingTransport(success([]))
        )
        self.assertEqual(empty_provider.nearby_transit(121.47, 31.23), [])

        stations = [
            poi(
                f"S-{index}",
                f"公交站 {index}",
                poi_type="交通设施服务;公交车站",
                typecode="150700",
                distance=str(distance),
            )
            for index, distance in enumerate([800, 100, 500, 200, 400, 300], start=1)
        ]
        transport = RecordingTransport(success(stations))
        provider = MapProvider("test-key", transport=transport)

        result = provider.nearby_transit(121.47, 31.23)

        self.assertEqual(len(result), 5)
        self.assertEqual([station.distance_m for station in result], [100, 200, 300, 400, 500])
        endpoint, parameters, _ = transport.calls[0]
        self.assertEqual(endpoint, AROUND_SEARCH_URL)
        self.assertEqual(parameters["radius"], "1000")

    def test_timeout_and_service_failure_are_clear(self) -> None:
        with self.subTest("timeout"):
            provider = MapProvider(
                "test-key", transport=RecordingTransport(TimeoutError())
            )
            with self.assertRaisesRegex(MapProviderError, "超时"):
                provider.search_places("测试餐厅")

        with self.subTest("service error"):
            provider = MapProvider(
                "test-key",
                transport=RecordingTransport(
                    {"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}
                ),
            )
            with self.assertRaisesRegex(MapProviderError, "INVALID_USER_KEY"):
                provider.nearby_transit(121.47, 31.23)

    def test_batch_location_stops_after_three_consecutive_service_errors(self) -> None:
        self.write_restaurants(
            [restaurant(index, f"失败餐厅{index}") for index in range(1, 6)]
        )
        transport = RecordingTransport(TimeoutError())

        results = resolve_pending_restaurants(
            MapProvider("test-key", transport=transport), self.path
        )

        self.assertEqual([item["status"] for item in results[:3]], ["error"] * 3)
        self.assertEqual(
            [item["status"] for item in results[3:]],
            ["skipped_service_failures"] * 2,
        )
        self.assertEqual(len(transport.calls), 3)


if __name__ == "__main__":
    unittest.main()
