"""Pure selection logic for choosing one restaurant uniformly."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Any


class EmptyRestaurantListError(ValueError):
    """Raised when a random choice is requested for an empty list."""


def active_restaurants(
    restaurants: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return selectable restaurants; missing V2 status means active."""

    return [
        restaurant
        for restaurant in restaurants
        if restaurant.get("selection_status", "active") == "active"
    ]


def choose_restaurant(
    restaurants: Sequence[dict[str, Any]],
    randint: Callable[[int, int], int] | None = None,
) -> dict[str, Any]:
    """Draw a display number in 1..N and return the matching restaurant."""

    eligible = active_restaurants(restaurants)
    total = len(eligible)
    if total == 0:
        raise EmptyRestaurantListError("活跃餐厅名单为空，无法随机选择")

    draw = randint or random.SystemRandom().randint
    number = draw(1, total)
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= total:
        raise ValueError(f"抽样器必须返回 1 到 {total} 之间的整数")

    return {
        "number": number,
        "total": total,
        "restaurant": eligible[number - 1],
    }
