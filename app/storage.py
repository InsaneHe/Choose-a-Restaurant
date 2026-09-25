"""Read and validate the restaurant JSON data source."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "restaurants.json"

REQUIRED_FIELDS = frozenset(
    {
        "id",
        "name",
        "type",
        "detail",
        "address",
        "longitude",
        "latitude",
        "amap_poi_id",
        "dianping_url",
        "location_status",
    }
)
LOCATION_STATUSES = frozenset(
    {"pending_location", "auto_resolved", "manual_confirmed"}
)
UPDATABLE_FIELDS = REQUIRED_FIELDS - {"id"}
LOCATION_IDENTITY_FIELDS = frozenset({"name", "address", "amap_poi_id"})
_WRITE_LOCK = threading.Lock()


class RestaurantDataError(ValueError):
    """Raised when the restaurant data file cannot be read or validated."""


class RestaurantConflictError(RestaurantDataError):
    """Raised when the data file changed after it was read."""


class RestaurantNotFoundError(RestaurantDataError):
    """Raised when a requested restaurant ID does not exist."""


class ManualLocationProtectedError(RestaurantConflictError):
    """Raised when automation attempts to overwrite a manual location."""


@dataclass(frozen=True)
class RestaurantSnapshot:
    restaurants: list[dict[str, Any]]
    version: str


def _data_error(path: Path, message: str) -> RestaurantDataError:
    return RestaurantDataError(f"餐厅数据文件 {path} 无效：{message}")


def _validate_nullable_text(
    record: dict[str, Any], field: str, index: int, path: Path
) -> None:
    value = record[field]
    if value is not None and not isinstance(value, str):
        raise _data_error(path, f"第 {index} 条记录的 {field} 必须是字符串或 null")


def _validate_dianping_url(value: Any, index: int, path: Path) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value:
        raise _data_error(path, f"第 {index} 条记录的 dianping_url 必须是字符串或 null")

    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise _data_error(path, f"第 {index} 条记录的 dianping_url 格式无效") from exc

    is_dianping_host = host == "dianping.com" or host.endswith(".dianping.com")
    merchant_prefixes = ("/shop/", "/shopshare/")
    is_merchant_path = any(
        parsed.path.startswith(prefix) and len(parsed.path) > len(prefix)
        for prefix in merchant_prefixes
    )
    if (
        parsed.scheme.lower() != "https"
        or not is_dianping_host
        or not is_merchant_path
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise _data_error(
            path,
            f"第 {index} 条记录的 dianping_url 必须是大众点评 HTTPS 商户链接",
        )


def _validate_coordinate(
    record: dict[str, Any], field: str, index: int, path: Path
) -> None:
    value = record[field]
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, (int, float))
    ):
        raise _data_error(path, f"第 {index} 条记录的 {field} 必须是数字或 null")

    if value is None:
        return

    lower, upper = (-180, 180) if field == "longitude" else (-90, 90)
    if not lower <= value <= upper:
        raise _data_error(
            path, f"第 {index} 条记录的 {field} 必须在 {lower} 到 {upper} 之间"
        )


def _validate_record(
    record: Any, index: int, seen_ids: set[int], path: Path
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise _data_error(path, f"第 {index} 条记录必须是 JSON 对象")

    missing = sorted(REQUIRED_FIELDS - record.keys())
    if missing:
        raise _data_error(path, f"第 {index} 条记录缺少字段：{', '.join(missing)}")

    restaurant_id = record["id"]
    if (
        isinstance(restaurant_id, bool)
        or not isinstance(restaurant_id, int)
        or restaurant_id <= 0
    ):
        raise _data_error(path, f"第 {index} 条记录的 id 必须是正整数")
    if restaurant_id in seen_ids:
        raise _data_error(path, f"餐厅 id {restaurant_id} 重复")
    seen_ids.add(restaurant_id)

    for field in ("name", "type", "detail"):
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            raise _data_error(path, f"第 {index} 条记录的 {field} 必须是非空字符串")

    for field in ("address", "amap_poi_id"):
        _validate_nullable_text(record, field, index, path)
    _validate_dianping_url(record["dianping_url"], index, path)

    for field in ("longitude", "latitude"):
        _validate_coordinate(record, field, index, path)

    if (record["longitude"] is None) != (record["latitude"] is None):
        raise _data_error(path, f"第 {index} 条记录的经纬度必须同时填写或同时为 null")

    status = record["location_status"]
    if status not in LOCATION_STATUSES:
        allowed = ", ".join(sorted(LOCATION_STATUSES))
        raise _data_error(
            path, f"第 {index} 条记录的 location_status 必须是：{allowed}"
        )

    has_coordinates = record["longitude"] is not None
    if status == "pending_location" and has_coordinates:
        raise _data_error(path, f"第 {index} 条待定位记录不能保存已确认坐标")
    if status in {"auto_resolved", "manual_confirmed"}:
        if not has_coordinates or not isinstance(record["address"], str) or not record[
            "address"
        ].strip():
            raise _data_error(
                path, f"第 {index} 条已定位记录必须同时包含地址和有效经纬度"
            )
    if status == "auto_resolved" and (
        not isinstance(record["amap_poi_id"], str)
        or not record["amap_poi_id"].strip()
    ):
        raise _data_error(path, f"第 {index} 条自动定位记录必须包含高德 POI ID")

    return record


def _validate_restaurants(data: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise _data_error(path, "顶层结构必须是 JSON 数组")

    seen_ids: set[int] = set()
    return [
        _validate_record(record, index, seen_ids, path)
        for index, record in enumerate(data, start=1)
    ]


def _decode_restaurants(raw: bytes, path: Path) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _data_error(path, "文件必须使用 UTF-8 编码") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _data_error(
            path,
            f"JSON 解析失败（第 {exc.lineno} 行，第 {exc.colno} 列）：{exc.msg}",
        ) from exc

    return _validate_restaurants(data, path)


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RestaurantDataError(f"无法读取餐厅数据文件 {path}：{exc}") from exc


def load_restaurant_snapshot(
    path: Path | str = DEFAULT_DATA_PATH,
) -> RestaurantSnapshot:
    """Read current data and its content version from disk."""

    data_path = Path(path)
    raw = _read_bytes(data_path)
    return RestaurantSnapshot(
        restaurants=_decode_restaurants(raw, data_path),
        version=hashlib.sha256(raw).hexdigest(),
    )


def load_restaurants(path: Path | str = DEFAULT_DATA_PATH) -> list[dict[str, Any]]:
    """Read and validate restaurants from disk on every call.

    The function never writes to *path* and does not retain an in-memory copy.
    """

    return load_restaurant_snapshot(path).restaurants


def save_restaurants(
    restaurants: Sequence[Mapping[str, Any]],
    expected_version: str,
    path: Path | str = DEFAULT_DATA_PATH,
) -> None:
    """Validate and atomically replace the file if its version is unchanged."""

    data_path = Path(path)
    candidate = [dict(record) for record in restaurants]
    _validate_restaurants(candidate, data_path)
    encoded = (
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    with _WRITE_LOCK:
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=data_path.parent,
                prefix=f".{data_path.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            current_raw = _read_bytes(data_path)
            current_version = hashlib.sha256(current_raw).hexdigest()
            if current_version != expected_version:
                raise RestaurantConflictError(
                    "餐厅数据文件在读取后已被修改；本次操作已取消，请刷新后重试"
                )

            os.replace(temporary_path, data_path)
            temporary_path = None
        except RestaurantDataError:
            raise
        except OSError as exc:
            raise RestaurantDataError(
                f"无法写入餐厅数据文件 {data_path}：{exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass


def create_restaurant(
    name: str,
    restaurant_type: str,
    detail: str,
    dianping_url: str | None = None,
    path: Path | str = DEFAULT_DATA_PATH,
) -> dict[str, Any]:
    snapshot = load_restaurant_snapshot(path)
    new_id = max((record["id"] for record in snapshot.restaurants), default=0) + 1
    new_record: dict[str, Any] = {
        "id": new_id,
        "name": name,
        "type": restaurant_type,
        "detail": detail,
        "address": None,
        "longitude": None,
        "latitude": None,
        "amap_poi_id": None,
        "dianping_url": dianping_url,
        "location_status": "pending_location",
    }
    updated = [*snapshot.restaurants, new_record]
    save_restaurants(updated, snapshot.version, path)
    return new_record


def update_restaurant(
    restaurant_id: int,
    changes: Mapping[str, Any],
    path: Path | str = DEFAULT_DATA_PATH,
) -> dict[str, Any]:
    unknown_fields = set(changes) - UPDATABLE_FIELDS
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise RestaurantDataError(f"不可修改字段：{names}")
    if not changes:
        raise RestaurantDataError("至少提供一个要修改的字段")

    snapshot = load_restaurant_snapshot(path)
    target_index = next(
        (
            index
            for index, record in enumerate(snapshot.restaurants)
            if record["id"] == restaurant_id
        ),
        None,
    )
    if target_index is None:
        raise RestaurantNotFoundError(f"未找到餐厅 id {restaurant_id}")

    original = snapshot.restaurants[target_index]
    updated_record = {**original, **changes}
    changed_identity_fields = {
        field
        for field in LOCATION_IDENTITY_FIELDS & changes.keys()
        if updated_record[field] != original[field]
    }
    if changed_identity_fields:
        updated_record["longitude"] = None
        updated_record["latitude"] = None
        updated_record["location_status"] = "pending_location"
        if "name" in changed_identity_fields:
            if "address" not in changes:
                updated_record["address"] = None
            if "amap_poi_id" not in changes:
                updated_record["amap_poi_id"] = None
        if "address" in changed_identity_fields and "amap_poi_id" not in changes:
            updated_record["amap_poi_id"] = None
        if "amap_poi_id" in changed_identity_fields and "address" not in changes:
            updated_record["address"] = None

    updated = list(snapshot.restaurants)
    updated[target_index] = updated_record
    save_restaurants(updated, snapshot.version, path)
    return updated_record


def delete_restaurant(
    restaurant_id: int, path: Path | str = DEFAULT_DATA_PATH
) -> dict[str, Any]:
    snapshot = load_restaurant_snapshot(path)
    deleted = next(
        (record for record in snapshot.restaurants if record["id"] == restaurant_id),
        None,
    )
    if deleted is None:
        raise RestaurantNotFoundError(f"未找到餐厅 id {restaurant_id}")

    updated = [
        record for record in snapshot.restaurants if record["id"] != restaurant_id
    ]
    save_restaurants(updated, snapshot.version, path)
    return deleted


def set_restaurant_location(
    restaurant_id: int,
    *,
    address: str,
    longitude: float,
    latitude: float,
    amap_poi_id: str | None,
    location_status: str,
    path: Path | str = DEFAULT_DATA_PATH,
    expected_version: str | None = None,
) -> dict[str, Any]:
    """Persist a confirmed location without bypassing conflict protection."""

    if location_status not in {"auto_resolved", "manual_confirmed"}:
        raise RestaurantDataError(
            "保存位置时 location_status 必须是 auto_resolved 或 manual_confirmed"
        )

    snapshot = load_restaurant_snapshot(path)
    if expected_version is not None and snapshot.version != expected_version:
        raise RestaurantConflictError(
            "餐厅数据文件在定位搜索期间已被修改；未保存旧搜索结果，请重新加载后再试"
        )
    target_index = next(
        (
            index
            for index, record in enumerate(snapshot.restaurants)
            if record["id"] == restaurant_id
        ),
        None,
    )
    if target_index is None:
        raise RestaurantNotFoundError(f"未找到餐厅 id {restaurant_id}")

    current = snapshot.restaurants[target_index]
    if (
        location_status == "auto_resolved"
        and current["location_status"] == "manual_confirmed"
    ):
        raise ManualLocationProtectedError(
            f"餐厅 id {restaurant_id} 已人工确认位置，自动定位不会覆盖"
        )

    updated_record = {
        **current,
        "address": address,
        "longitude": longitude,
        "latitude": latitude,
        "amap_poi_id": amap_poi_id,
        "location_status": location_status,
    }
    updated = list(snapshot.restaurants)
    updated[target_index] = updated_record
    save_restaurants(updated, snapshot.version, path)
    return updated_record
