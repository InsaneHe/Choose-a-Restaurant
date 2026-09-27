import json
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.dianping import (
    DianpingInputError,
    MAX_DIANPING_URL_LENGTH,
    MAX_SHARE_INPUT_LENGTH,
    normalize_dianping_url,
    parse_dianping_input,
)
from app.main import DianpingParseRequest, RestaurantCreate, create_app
from app.storage import RestaurantDataError, create_restaurant, load_restaurants, update_restaurant


MOBILE_URL = (
    "https://m.dianping.com/shopinfo/G8vQ1zgGBMlcfSli"
    "?msource=Appshare2021&utm_source=shop_share&shoptype=10"
    "&shopcategoryid=114&cityid=1&isoversea=0"
)
NORMALIZED_MOBILE_URL = (
    "https://m.dianping.com/shopinfo/G8vQ1zgGBMlcfSli"
    "?shoptype=10&shopcategoryid=114&cityid=1&isoversea=0"
)
FULL_SHARE = f"""【青鹤谷韩国料理(总店)】
★★★★☆ 4.7
¥187/人
虹桥镇商圈 韩式料理
虹莘路3998号帝宝大厦2楼
{MOBILE_URL}"""


def restaurant(restaurant_id: int = 1) -> dict[str, object]:
    return {
        "id": restaurant_id,
        "name": "原餐厅",
        "type": "正餐",
        "detail": "测试",
        "address": None,
        "longitude": None,
        "latitude": None,
        "amap_poi_id": None,
        "dianping_url": None,
        "location_status": "pending_location",
        "selection_status": "active",
        "tags": [],
    }


class DianpingParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).parent / f".v2-03-{uuid4().hex}.json"
        self.addCleanup(self.path.unlink, missing_ok=True)

    def write_json(self, value: object) -> None:
        self.path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def test_full_mobile_share_extracts_only_confirmable_clues(self) -> None:
        result = parse_dianping_input(FULL_SHARE)

        self.assertEqual(result.name_suggestion, "青鹤谷韩国料理(总店)")
        self.assertEqual(result.address_hint, "虹莘路3998号帝宝大厦2楼")
        self.assertEqual(result.url, NORMALIZED_MOBILE_URL)
        self.assertFalse(result.requires_name)
        self.assertNotIn("4.7", result.url)
        self.assertNotIn("187", result.url)

    def test_mobile_url_only_requires_a_manually_supplied_name(self) -> None:
        result = parse_dianping_input(MOBILE_URL)

        self.assertIsNone(result.name_suggestion)
        self.assertIsNone(result.address_hint)
        self.assertTrue(result.requires_name)
        self.assertEqual(result.url, NORMALIZED_MOBILE_URL)

    def test_pc_shop_and_shopshare_links_remain_supported(self) -> None:
        cases = [
            "https://www.dianping.com/shop/abc123",
            "https://m.dianping.com/shopshare/OldPcCompatible",
            "https://dianping.com/shop/merchant_1",
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(normalize_dianping_url(value), value)

    def test_unicode_name_and_alphanumeric_merchant_id_round_trip(self) -> None:
        share = "【鼎泰豐 Café Branch】\nhttps://m.dianping.com/shopinfo/Az09_-xY"

        result = parse_dianping_input(share)

        self.assertEqual(result.name_suggestion, "鼎泰豐 Café Branch")
        self.assertTrue(result.url.endswith("/Az09_-xY"))

    def test_markdown_duplicate_of_same_url_is_not_ambiguous(self) -> None:
        escaped = MOBILE_URL.replace("&", r"\&").replace("_", r"\_")
        share = f"【测试店】\n[{MOBILE_URL}]({escaped})"

        result = parse_dianping_input(share)

        self.assertEqual(result.url, NORMALIZED_MOBILE_URL)

    def test_disallowed_scheme_host_path_and_id_are_rejected(self) -> None:
        invalid = [
            "http://m.dianping.com/shopinfo/abc123",
            "https://m.dianping.com.evil.example/shopinfo/abc123",
            "https://m.dianping.com./shopinfo/abc123",
            "https://evil.example/shop/abc123",
            "https://www.dianping.com/shopinfo/abc123",
            "https://m.dianping.com/review/abc123",
            "https://m.dianping.com/shopinfo/a%2Fb",
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(DianpingInputError):
                    parse_dianping_input(value)

    def test_missing_url_conflicting_urls_and_multiple_names_are_clear(self) -> None:
        invalid = [
            "【只有名称】\n没有链接",
            "m.dianping.com/shopinfo/NoScheme",
            (
                "【冲突店】\nhttps://m.dianping.com/shopinfo/one\n"
                "https://m.dianping.com/shopinfo/two"
            ),
            "【甲店】\n【乙店】\nhttps://m.dianping.com/shopinfo/one",
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(DianpingInputError):
                    parse_dianping_input(value)

    def test_input_length_is_bounded(self) -> None:
        with self.assertRaisesRegex(DianpingInputError, "过长"):
            parse_dianping_input("x" * (MAX_SHARE_INPUT_LENGTH + 1))
        with self.assertRaisesRegex(DianpingInputError, "过长"):
            normalize_dianping_url(
                "https://m.dianping.com/shopinfo/" + "a" * MAX_DIANPING_URL_LENGTH
            )

    def test_html_like_name_is_data_and_frontend_uses_text_content(self) -> None:
        result = parse_dianping_input(
            "【<img src=x onerror=alert(1)>】\n"
            "https://m.dianping.com/shopinfo/HtmlCase"
        )
        script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertEqual(result.name_suggestion, "<img src=x onerror=alert(1)>")
        self.assertIn("dianpingPreviewName.textContent", script)
        self.assertNotIn("dianpingPreviewName.innerHTML", script)

    def test_storage_accepts_mobile_path_and_invalid_edit_preserves_file(self) -> None:
        self.write_json([restaurant()])
        created = create_restaurant(
            "手机链接餐厅", "正餐", "测试", NORMALIZED_MOBILE_URL, self.path
        )
        before = self.path.read_bytes()

        with self.assertRaisesRegex(RestaurantDataError, "HTTPS 商户链接"):
            update_restaurant(
                created["id"],
                {"dianping_url": "https://m.dianping.com.evil.example/shopinfo/x"},
                self.path,
            )

        self.assertEqual(self.path.read_bytes(), before)

    def test_parse_api_then_create_keeps_location_pending_and_tags_empty(self) -> None:
        self.write_json([])
        application = create_app(self.path)

        def endpoint(path: str, method: str):
            return next(
                route.endpoint
                for route in application.routes
                if getattr(route, "path", None) == path
                and method in getattr(route, "methods", set())
            )

        parsed = endpoint("/api/dianping/parse", "POST")(
            DianpingParseRequest(text=FULL_SHARE)
        )
        created = endpoint("/api/restaurants", "POST")(
            RestaurantCreate(
                name=parsed["name_suggestion"],
                type="正餐",
                detail="韩式料理",
                dianping_url=parsed["url"],
            )
        )

        self.assertEqual(created["name"], "青鹤谷韩国料理(总店)")
        self.assertEqual(created["tags"], [])
        self.assertEqual(created["location_status"], "pending_location")
        self.assertIsNone(created["address"])
        self.assertIsNone(created["longitude"])
        self.assertIsNone(created["latitude"])
        self.assertIsNone(created["amap_poi_id"])
        self.assertEqual(load_restaurants(self.path), [created])

    def test_parse_api_error_does_not_create_a_record(self) -> None:
        self.write_json([])
        application = create_app(self.path)
        parse_endpoint = next(
            route.endpoint
            for route in application.routes
            if getattr(route, "path", None) == "/api/dianping/parse"
        )

        with self.assertRaises(HTTPException) as context:
            parse_endpoint(DianpingParseRequest(text="https://evil.example/shop/x"))

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(load_restaurants(self.path), [])

    def test_page_requires_preview_adoption_and_preserves_location_flow(self) -> None:
        page = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="dianping-share-input"', page)
        self.assertIn('id="dianping-preview"', page)
        self.assertIn('id="use-dianping-button"', page)
        self.assertIn('apiRequest("/api/dianping/parse"', script)
        self.assertIn("请先解析并采用点评分享预览", script)
        self.assertIn("保存后仍须按高德候选确认具体分店", page)


if __name__ == "__main__":
    unittest.main()
