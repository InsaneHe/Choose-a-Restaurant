import json
import unittest
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.map_provider import (
    TRANSIT_ROUTE_URL,
    MapProvider,
    MapProviderError,
    PublicTransitRoute,
)
from app.ranking import (
    GroupRandomUnavailableError,
    GroupRankingState,
    rank_restaurants,
)
from app.storage import load_restaurant_snapshot, set_restaurant_location
from tests.fixtures.amap_responses import transit_success


def participant(participant_id: str, name: str) -> dict[str, Any]:
    return {
        "participant_id": participant_id,
        "name": name,
        "address": f"上海市{name}出发点",
        "longitude": 121.4,
        "latitude": 31.2,
        "amap_poi_id": f"ORIGIN-{participant_id}",
    }


def restaurant(restaurant_id: int, name: str) -> dict[str, Any]:
    return {
        "id": restaurant_id,
        "name": name,
        "type": "正餐",
        "detail": "测试菜系",
        "address": f"上海市{name}地址",
        "longitude": 121.5 + restaurant_id / 1000,
        "latitude": 31.25,
        "amap_poi_id": f"DEST-{restaurant_id}",
        "dianping_url": None,
        "location_status": "manual_confirmed",
    }


def route(seconds: int) -> PublicTransitRoute:
    return PublicTransitRoute(seconds, "测试公共交通方案", ("测试地铁线",))


class RankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.participants = [participant("p1", "甲"), participant("p2", "乙")]
        self.restaurants = [restaurant(1, "餐厅甲"), restaurant(2, "餐厅乙")]
        self.path = Path(__file__).parent / f".ranking-{uuid4().hex}.json"
        self.addCleanup(self.path.unlink, missing_ok=True)

    def test_total_seconds_is_primary_sort_key(self) -> None:
        durations = {
            (1, "p1"): 20 * 60,
            (1, "p2"): 40 * 60,
            (2, "p1"): 30 * 60,
            (2, "p2"): 35 * 60,
        }

        result = rank_restaurants(
            self.restaurants,
            self.participants,
            lambda person, place: route(durations[(place["id"], person["participant_id"])]),
        )

        self.assertEqual([item["restaurant"]["id"] for item in result["ranked"]], [1, 2])
        self.assertEqual(result["ranked"][0]["total_seconds"], 60 * 60)

    def test_ties_use_slowest_person_then_restaurant_id(self) -> None:
        restaurants = [restaurant(3, "三号"), restaurant(2, "二号"), restaurant(1, "一号")]
        durations = {
            (1, "p1"): 30,
            (1, "p2"): 30,
            (2, "p1"): 20,
            (2, "p2"): 40,
            (3, "p1"): 30,
            (3, "p2"): 30,
        }
        result = rank_restaurants(
            restaurants,
            self.participants,
            lambda person, place: route(durations[(place["id"], person["participant_id"])]),
        )

        self.assertEqual([item["restaurant"]["id"] for item in result["ranked"]], [1, 3, 2])

    def test_no_route_excludes_restaurant_without_zero_duration(self) -> None:
        def lookup(person: dict[str, Any], place: dict[str, Any]) -> PublicTransitRoute | None:
            if place["id"] == 1 and person["participant_id"] == "p2":
                return None
            return route(600)

        result = rank_restaurants(self.restaurants, self.participants, lookup)

        self.assertEqual([item["restaurant"]["id"] for item in result["ranked"]], [2])
        self.assertEqual(result["excluded"][0]["code"], "no_route")
        self.assertTrue(result["coverage_complete"])

    def test_service_error_marks_coverage_incomplete(self) -> None:
        def lookup(person: dict[str, Any], place: dict[str, Any]) -> PublicTransitRoute:
            raise MapProviderError("合成服务失败")

        result = rank_restaurants(self.restaurants, self.participants, lookup)

        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["ranked"], [])
        self.assertTrue(all(item["code"] == "route_service_error" for item in result["excluded"]))
        self.assertTrue(all("合成服务失败" in item["reason"] for item in result["excluded"]))

    def test_fastest_valid_amap_plan_and_cost_field(self) -> None:
        calls: list[tuple[str, dict[str, str], float]] = []

        def transport(
            endpoint: str, parameters: dict[str, str], timeout: float
        ) -> dict[str, Any]:
            calls.append((endpoint, dict(parameters), timeout))
            return transit_success([1800, 900, 1200])

        provider = MapProvider("test-key", transport=transport)
        fastest = provider.best_public_transit_route(
            121.4,
            31.2,
            121.5,
            31.25,
            origin_poi_id="ORIGIN",
            destination_poi_id="DEST",
        )

        self.assertIsNotNone(fastest)
        self.assertEqual(fastest.duration_seconds, 900)
        endpoint, parameters, timeout = calls[0]
        self.assertEqual(endpoint, TRANSIT_ROUTE_URL)
        self.assertEqual(parameters["show_fields"], "cost")
        self.assertEqual(parameters["city1"], "021")
        self.assertEqual(parameters["city2"], "021")
        self.assertEqual(parameters["originpoi"], "ORIGIN")
        self.assertEqual(parameters["destinationpoi"], "DEST")
        self.assertEqual(timeout, 5.0)

    def test_location_correction_invalidates_random_until_reranked(self) -> None:
        self.path.write_text(
            json.dumps([restaurant(1, "可更正餐厅")], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        state = GroupRankingState()
        first = rank_restaurants(
            load_restaurant_snapshot(self.path).restaurants,
            self.participants,
            lambda person, place: route(900),
        )
        first["data_version"] = load_restaurant_snapshot(self.path).version
        first_id = state.record(first)
        self.assertIsNotNone(first_id)

        set_restaurant_location(
            1,
            address="上海市更正后地址",
            longitude=121.6,
            latitude=31.3,
            amap_poi_id="DEST-NEW",
            location_status="manual_confirmed",
            path=self.path,
        )
        with self.assertRaisesRegex(GroupRandomUnavailableError, "已失效"):
            state.draw(
                first_id,
                load_restaurant_snapshot(self.path).version,
                lambda lower, upper: lower,
            )

        second = rank_restaurants(
            load_restaurant_snapshot(self.path).restaurants,
            self.participants,
            lambda person, place: route(600),
        )
        second["data_version"] = load_restaurant_snapshot(self.path).version
        second_id = state.record(second)
        draw = state.draw(
            second_id,
            load_restaurant_snapshot(self.path).version,
            lambda lower, upper: upper,
        )
        self.assertEqual(draw["total"], 1)
        self.assertEqual(draw["restaurant"]["id"], 1)

    def test_incomplete_result_is_not_random_eligible(self) -> None:
        state = GroupRankingState()
        result = rank_restaurants(
            self.restaurants,
            self.participants,
            lambda person, place: route(600),
        )
        result["coverage_complete"] = False
        result["data_version"] = "version"

        self.assertIsNone(state.record(result))
        with self.assertRaisesRegex(GroupRandomUnavailableError, "没有最近一次"):
            state.draw("missing", "version")


if __name__ == "__main__":
    unittest.main()
