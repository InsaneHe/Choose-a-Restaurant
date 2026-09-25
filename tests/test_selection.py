import unittest

from app.selection import EmptyRestaurantListError, choose_restaurant


class ChooseRestaurantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.restaurants = [
            {"id": 10, "name": "第一家", "type": "正餐"},
            {"id": 20, "name": "第二家", "type": "小吃"},
            {"id": 30, "name": "第三家", "type": "烧烤"},
        ]

    def test_lower_boundary_maps_number_one_to_first_item(self) -> None:
        result = choose_restaurant(self.restaurants, lambda lower, upper: lower)

        self.assertEqual(result["number"], 1)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["restaurant"]["id"], 10)

    def test_upper_boundary_maps_number_n_to_last_item(self) -> None:
        result = choose_restaurant(self.restaurants, lambda lower, upper: upper)

        self.assertEqual(result["number"], 3)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["restaurant"]["id"], 30)

    def test_empty_list_has_clear_error(self) -> None:
        with self.assertRaisesRegex(EmptyRestaurantListError, "名单为空"):
            choose_restaurant([])


if __name__ == "__main__":
    unittest.main()
