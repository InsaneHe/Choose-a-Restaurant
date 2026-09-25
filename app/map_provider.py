"""AMap POI, station, and public-transit boundary used by W03/W04.

The provider accepts an injectable transport so tests never need a real key or
network connection.  Production requests use only the backend Web Service key.
"""

from __future__ import annotations

import json
import math
import re
import socket
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from opencc import OpenCC


TEXT_SEARCH_URL = "https://restapi.amap.com/v5/place/text"
AROUND_SEARCH_URL = "https://restapi.amap.com/v5/place/around"
TRANSIT_ROUTE_URL = "https://restapi.amap.com/v5/direction/transit/integrated"
SHANGHAI_REGION = "上海市"
SHANGHAI_CITY_CODE = "021"
RESTAURANT_TYPE = "050000"
TRANSIT_TYPES = "150500|150700"
MAX_QUERY_VARIANTS = 6

Transport = Callable[[str, Mapping[str, str], float], Mapping[str, Any]]

_TO_SIMPLIFIED = OpenCC("t2s")
_TO_TRADITIONAL = OpenCC("s2t")
_LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'&.-]{2,}")
_GENERIC_FOREIGN_WORDS = {
    "and",
    "bar",
    "cafe",
    "restaurant",
    "the",
}


class MapProviderError(RuntimeError):
    """Raised when AMap cannot provide a usable response."""


class MapConfigurationError(MapProviderError):
    """Raised when required AMap backend configuration is absent."""


@dataclass(frozen=True)
class PlaceCandidate:
    poi_id: str
    name: str
    address: str | None
    province: str | None
    city: str | None
    district: str | None
    longitude: float | None
    latitude: float | None
    poi_type: str | None
    typecode: str | None

    @property
    def complete_for_location(self) -> bool:
        return bool(
            self.poi_id
            and self.name
            and self.address
            and self.longitude is not None
            and self.latitude is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransitStation:
    poi_id: str
    name: str
    category: str
    address: str | None
    longitude: float | None
    latitude: float | None
    distance_m: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublicTransitRoute:
    duration_seconds: int
    summary: str
    segments: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _add_variant(variants: list[str], value: str) -> None:
    candidate = " ".join(value.split()).strip()
    if candidate and candidate not in variants and len(variants) < MAX_QUERY_VARIANTS:
        variants.append(candidate)


def build_query_variants(name: str) -> list[str]:
    """Build bounded variants without inventing translations or transliterations."""

    variants: list[str] = []
    original = name.strip()
    normalized = unicodedata.normalize("NFKC", original)
    _add_variant(variants, original)
    _add_variant(variants, normalized)
    _add_variant(variants, _TO_SIMPLIFIED.convert(normalized))
    _add_variant(variants, _TO_TRADITIONAL.convert(normalized))

    if any(character.isascii() and character.isalpha() for character in normalized):
        _add_variant(variants, normalized.casefold())
        _add_variant(variants, normalized.upper())

    tokens = sorted(
        {
            token
            for token in _LATIN_TOKEN.findall(normalized)
            if token.casefold() not in _GENERIC_FOREIGN_WORDS
        },
        key=lambda token: (-len(token), token.casefold()),
    )
    for token in tokens[:2]:
        _add_variant(variants, token)

    return variants[:MAX_QUERY_VARIANTS]


def canonical_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    simplified = _TO_SIMPLIFIED.convert(normalized)
    return "".join(character for character in simplified if character.isalnum())


def choose_auto_candidate(
    restaurant_name: str, candidates: list[PlaceCandidate]
) -> PlaceCandidate | None:
    """Return a candidate only for a single complete standardized exact result."""

    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if not candidate.complete_for_location:
        return None
    if canonical_name(candidate.name) != canonical_name(restaurant_name):
        return None
    return candidate


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _coordinates(value: Any) -> tuple[float | None, float | None]:
    if not isinstance(value, str):
        return None, None
    try:
        longitude_text, latitude_text = value.split(",", maxsplit=1)
        longitude = float(longitude_text)
        latitude = float(latitude_text)
    except (TypeError, ValueError):
        return None, None
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None, None
    return longitude, latitude


def _positive_seconds(value: Any) -> int | None:
    try:
        seconds = round(float(value))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _as_mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _transit_segment_texts(value: Any) -> tuple[str, ...]:
    descriptions: list[str] = []
    for segment in _as_mapping_list(value):
        walking = segment.get("walking")
        if isinstance(walking, Mapping):
            instructions = [
                _optional_string(step.get("instruction"))
                for step in _as_mapping_list(walking.get("steps"))
            ]
            instructions = [item for item in instructions if item]
            if instructions:
                descriptions.append("步行：" + "；".join(instructions))

        bus = segment.get("bus")
        if isinstance(bus, Mapping):
            for busline in _as_mapping_list(
                bus.get("buslines", bus.get("busline"))
            ):
                line_name = _optional_string(busline.get("name"))
                departure = busline.get("departure_stop")
                arrival = busline.get("arrival_stop")
                departure_name = (
                    _optional_string(departure.get("name"))
                    if isinstance(departure, Mapping)
                    else None
                )
                arrival_name = (
                    _optional_string(arrival.get("name"))
                    if isinstance(arrival, Mapping)
                    else None
                )
                if line_name:
                    stops = (
                        f"（{departure_name} → {arrival_name}）"
                        if departure_name and arrival_name
                        else ""
                    )
                    descriptions.append(f"公交/地铁：{line_name}{stops}")

        railway = segment.get("railway")
        if isinstance(railway, Mapping):
            railway_name = _optional_string(railway.get("name")) or _optional_string(
                railway.get("trip")
            )
            if railway_name:
                descriptions.append(f"铁路：{railway_name}")

        taxi = segment.get("taxi")
        if isinstance(taxi, Mapping) and taxi:
            descriptions.append("出租车接驳")

    return tuple(descriptions)


def _parse_public_transit_route(value: Any) -> PublicTransitRoute | None:
    if not isinstance(value, Mapping):
        return None
    cost = value.get("cost")
    duration_seconds = (
        _positive_seconds(cost.get("duration")) if isinstance(cost, Mapping) else None
    )
    if duration_seconds is None:
        return None
    segments = _transit_segment_texts(value.get("segments"))
    summary = " → ".join(segments) if segments else "高德公共交通方案（无分段文字）"
    return PublicTransitRoute(
        duration_seconds=duration_seconds,
        summary=summary,
        segments=segments,
    )


def _is_shanghai(poi: Mapping[str, Any]) -> bool:
    city = _optional_string(poi.get("cityname"))
    adcode = _optional_string(poi.get("adcode"))
    if city is not None and "上海" not in city:
        return False
    if adcode is not None and not adcode.startswith("31"):
        return False
    return True


def _parse_candidate(poi: Any) -> PlaceCandidate | None:
    if not isinstance(poi, Mapping) or not _is_shanghai(poi):
        return None
    poi_id = _optional_string(poi.get("id"))
    name = _optional_string(poi.get("name"))
    if poi_id is None or name is None:
        return None
    longitude, latitude = _coordinates(poi.get("location"))
    return PlaceCandidate(
        poi_id=poi_id,
        name=name,
        address=_optional_string(poi.get("address")),
        province=_optional_string(poi.get("pname")),
        city=_optional_string(poi.get("cityname")),
        district=_optional_string(poi.get("adname")),
        longitude=longitude,
        latitude=latitude,
        poi_type=_optional_string(poi.get("type")),
        typecode=_optional_string(poi.get("typecode")),
    )


def _haversine_distance_m(
    origin_longitude: float,
    origin_latitude: float,
    target_longitude: float,
    target_latitude: float,
) -> int:
    earth_radius_m = 6_371_000
    origin_latitude_radians = math.radians(origin_latitude)
    target_latitude_radians = math.radians(target_latitude)
    latitude_delta = math.radians(target_latitude - origin_latitude)
    longitude_delta = math.radians(target_longitude - origin_longitude)
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(origin_latitude_radians)
        * math.cos(target_latitude_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return round(earth_radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))


class MapProvider:
    def __init__(
        self,
        web_service_key: str | None,
        *,
        transport: Transport | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._web_service_key = web_service_key
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._web_service_key)

    def _request(
        self, endpoint: str, parameters: Mapping[str, str]
    ) -> Mapping[str, Any]:
        if not self._web_service_key:
            raise MapConfigurationError("未配置高德 Web 服务密钥")

        request_parameters = {**parameters, "key": self._web_service_key}
        try:
            if self._transport is not None:
                payload = self._transport(
                    endpoint, request_parameters, self._timeout_seconds
                )
            else:
                url = f"{endpoint}?{urlencode(request_parameters)}"
                request = Request(
                    url,
                    headers={"Accept": "application/json", "User-Agent": "ChooseRestaurant/0.3"},
                )
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, socket.timeout) as exc:
            raise MapProviderError("高德请求超时") from exc
        except HTTPError as exc:
            raise MapProviderError(f"高德请求失败（HTTP {exc.code}）") from exc
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise MapProviderError("高德请求超时") from exc
            raise MapProviderError("无法连接高德服务") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MapProviderError("高德返回了无法解析的数据") from exc
        except MapProviderError:
            raise
        except Exception as exc:
            raise MapProviderError("高德请求失败") from exc

        if not isinstance(payload, Mapping):
            raise MapProviderError("高德返回结构无效")
        if str(payload.get("status")) != "1":
            info = _optional_string(payload.get("info")) or "未知错误"
            infocode = _optional_string(payload.get("infocode"))
            suffix = f"（{infocode}）" if infocode else ""
            raise MapProviderError(f"高德服务返回错误：{info}{suffix}")
        return payload

    def search_places(self, restaurant_name: str) -> list[PlaceCandidate]:
        candidates_by_id: dict[str, PlaceCandidate] = {}
        for query in build_query_variants(restaurant_name):
            payload = self._request(
                TEXT_SEARCH_URL,
                {
                    "keywords": query,
                    "types": RESTAURANT_TYPE,
                    "region": SHANGHAI_REGION,
                    "city_limit": "true",
                    "page_size": "20",
                    "page_num": "1",
                },
            )
            pois = payload.get("pois", [])
            if not isinstance(pois, list):
                raise MapProviderError("高德返回的 POI 列表结构无效")
            for raw_poi in pois:
                candidate = _parse_candidate(raw_poi)
                if candidate is not None:
                    candidates_by_id.setdefault(candidate.poi_id, candidate)
        return list(candidates_by_id.values())

    def search_origins(self, query: str, *, limit: int = 10) -> list[PlaceCandidate]:
        """Search one Shanghai origin query without restaurant type filtering."""

        payload = self._request(
            TEXT_SEARCH_URL,
            {
                "keywords": query.strip(),
                "region": SHANGHAI_REGION,
                "city_limit": "true",
                "page_size": str(limit),
                "page_num": "1",
            },
        )
        pois = payload.get("pois", [])
        if not isinstance(pois, list):
            raise MapProviderError("高德返回的出发地候选结构无效")
        candidates_by_id: dict[str, PlaceCandidate] = {}
        for raw_poi in pois:
            candidate = _parse_candidate(raw_poi)
            if candidate is not None:
                candidates_by_id.setdefault(candidate.poi_id, candidate)
        return list(candidates_by_id.values())[:limit]

    def best_public_transit_route(
        self,
        origin_longitude: float,
        origin_latitude: float,
        destination_longitude: float,
        destination_latitude: float,
        *,
        origin_poi_id: str | None = None,
        destination_poi_id: str | None = None,
        alternatives: int = 3,
    ) -> PublicTransitRoute | None:
        """Return the fastest valid AMap transit plan for one origin/destination."""

        parameters = {
            "origin": f"{origin_longitude:.6f},{origin_latitude:.6f}",
            "destination": (
                f"{destination_longitude:.6f},{destination_latitude:.6f}"
            ),
            "city1": SHANGHAI_CITY_CODE,
            "city2": SHANGHAI_CITY_CODE,
            "AlternativeRoute": str(max(1, min(alternatives, 10))),
            "show_fields": "cost",
        }
        if origin_poi_id and destination_poi_id:
            parameters["originpoi"] = origin_poi_id
            parameters["destinationpoi"] = destination_poi_id

        payload = self._request(TRANSIT_ROUTE_URL, parameters)
        route = payload.get("route")
        if not isinstance(route, Mapping):
            return None
        transits = route.get("transits", [])
        if not isinstance(transits, list):
            raise MapProviderError("高德返回的公交方案结构无效")
        plans = [
            plan
            for plan in (_parse_public_transit_route(item) for item in transits)
            if plan is not None
        ]
        return min(plans, key=lambda plan: plan.duration_seconds, default=None)

    def nearby_transit(
        self, longitude: float, latitude: float, *, radius_m: int = 1000, limit: int = 5
    ) -> list[TransitStation]:
        payload = self._request(
            AROUND_SEARCH_URL,
            {
                "location": f"{longitude:.6f},{latitude:.6f}",
                "radius": str(radius_m),
                "types": TRANSIT_TYPES,
                "sortrule": "distance",
                "page_size": str(limit),
                "page_num": "1",
            },
        )
        pois = payload.get("pois", [])
        if not isinstance(pois, list):
            raise MapProviderError("高德返回的站点列表结构无效")

        stations: list[TransitStation] = []
        seen_ids: set[str] = set()
        for poi in pois:
            if not isinstance(poi, Mapping) or not _is_shanghai(poi):
                continue
            poi_id = _optional_string(poi.get("id"))
            name = _optional_string(poi.get("name"))
            if poi_id is None or name is None or poi_id in seen_ids:
                continue
            seen_ids.add(poi_id)
            station_longitude, station_latitude = _coordinates(poi.get("location"))
            distance_text = _optional_string(poi.get("distance"))
            try:
                distance_m = round(float(distance_text)) if distance_text else None
            except ValueError:
                distance_m = None
            if (
                distance_m is None
                and station_longitude is not None
                and station_latitude is not None
            ):
                distance_m = _haversine_distance_m(
                    longitude, latitude, station_longitude, station_latitude
                )
            if distance_m is None or distance_m > radius_m:
                continue

            poi_type = _optional_string(poi.get("type")) or ""
            typecode = _optional_string(poi.get("typecode")) or ""
            if "地铁" in poi_type or "地铁" in name or typecode.startswith("1505"):
                category = "地铁站"
            elif "公交" in poi_type or "公交" in name or typecode.startswith("1507"):
                category = "公交站"
            else:
                category = "公共交通站"

            stations.append(
                TransitStation(
                    poi_id=poi_id,
                    name=name,
                    category=category,
                    address=_optional_string(poi.get("address")),
                    longitude=station_longitude,
                    latitude=station_latitude,
                    distance_m=distance_m,
                )
            )

        return sorted(stations, key=lambda station: station.distance_m)[:limit]
