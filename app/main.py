"""FastAPI entry point for restaurant management, maps, and group ranking."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.dianping import DianpingInputError, parse_dianping_input
from app.credentials import (
    AmapCredentials,
    CredentialStore,
    CredentialStoreError,
)
from app.location_service import resolve_pending_restaurants
from app.map_provider import (
    MapConfigurationError,
    MapProvider,
    MapProviderError,
    choose_auto_candidate,
)
from app.selection import (
    EmptyRestaurantListError,
    active_restaurants,
    choose_restaurant,
)
from app.ranking import (
    GroupRandomUnavailableError,
    GroupRankingError,
    GroupRankingState,
    perform_group_ranking,
)
from app.storage import (
    DEFAULT_DATA_PATH,
    RestaurantConflictError,
    RestaurantDataError,
    RestaurantNotFoundError,
    create_restaurant,
    delete_restaurant,
    import_restaurants_json,
    load_restaurant_snapshot,
    load_restaurants,
    set_restaurant_location,
    set_restaurant_selection_status,
    update_restaurant,
)
from app.runtime import RuntimePaths


STATIC_DIR = Path(__file__).resolve().parent / "static"


class RestaurantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    detail: str
    dianping_url: str | None = None
    tags: list[str] = Field(default_factory=list)


class RestaurantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    type: str | None = None
    detail: str | None = None
    address: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    amap_poi_id: str | None = None
    dianping_url: str | None = None
    location_status: str | None = None
    tags: list[str] = Field(default_factory=list)


class RestaurantLocationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str
    longitude: float
    latitude: float
    amap_poi_id: str | None = None


class RestaurantSelectionStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection_status: Literal["active", "archived"]


class DianpingParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class AmapSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    web_service_key: str
    js_api_key: str
    js_security_key: str


class RestaurantImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_text: str = Field(max_length=5 * 1024 * 1024)


class ParticipantLocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_id: str
    name: str
    address: str
    longitude: float
    latitude: float
    amap_poi_id: str | None = None


class GroupRankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participants: list[ParticipantLocationInput]


class GroupRandomRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ranking_id: str


def _raise_mutation_error(exc: RestaurantDataError) -> None:
    if isinstance(exc, RestaurantConflictError):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(exc, RestaurantNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    else:
        status_code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _raise_map_error(exc: MapProviderError) -> None:
    status_code = 503 if isinstance(exc, MapConfigurationError) else 502
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def create_app(
    data_path: Path | str = DEFAULT_DATA_PATH,
    randint: Callable[[int, int], int] | None = None,
    map_provider: MapProvider | None = None,
    js_api_key: str | None = None,
    js_security_code: str | None = None,
    credential_store: CredentialStore | None = None,
    runtime_paths: RuntimePaths | None = None,
    health_token: str | None = None,
    directory_opener: Callable[[Path], None] | None = None,
) -> FastAPI:
    """Create the app; injectable path/sampler keep tests off production data."""

    restaurant_path = Path(data_path)
    effective_paths = runtime_paths or RuntimePaths(
        False,
        restaurant_path.parent,
        restaurant_path,
        restaurant_path.parent / "backups",
        None,
    )
    if credential_store is not None:
        try:
            stored_credentials = credential_store.load()
        except CredentialStoreError as exc:
            raise RuntimeError("无法读取当前用户的高德配置") from exc
    else:
        stored_credentials = None
    runtime_credentials = stored_credentials or AmapCredentials(
        web_service_key=os.getenv("AMAP_WEB_SERVICE_KEY", ""),
        js_api_key=os.getenv("AMAP_JS_API_KEY", ""),
        js_security_key=(
            os.getenv("AMAP_JS_SECURITY_KEY")
            or os.getenv("AMAP_SECURITY_JS_CODE")
            or ""
        ),
    )
    if js_api_key is not None:
        runtime_credentials = AmapCredentials(
            runtime_credentials.web_service_key,
            js_api_key,
            runtime_credentials.js_security_key,
        )
    if js_security_code is not None:
        runtime_credentials = AmapCredentials(
            runtime_credentials.web_service_key,
            runtime_credentials.js_api_key,
            js_security_code,
        )

    def current_provider() -> MapProvider:
        return map_provider or MapProvider(runtime_credentials.web_service_key)

    def open_data_directory(path: Path) -> None:
        if directory_opener is not None:
            directory_opener(path)
            return
        if os.name != "nt":
            raise OSError("打开数据目录只支持 Windows")
        os.startfile(path)  # type: ignore[attr-defined]

    group_ranking_state = GroupRankingState()
    application = FastAPI(title="餐厅选择", version="0.8.0")
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/", include_in_schema=False)
    def homepage() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/api/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "instance": health_token}

    @application.get("/api/runtime/info")
    def runtime_info() -> dict[str, object]:
        return {
            "mode": "packaged" if effective_paths.packaged else "source",
            "data_path": str(restaurant_path.resolve()),
            "data_directory": str(restaurant_path.resolve().parent),
            "credential_storage": (
                "windows_current_user" if credential_store is not None else "environment"
            ),
        }

    @application.post("/api/runtime/open-data-directory")
    def show_data_directory() -> dict[str, object]:
        try:
            open_data_directory(restaurant_path.resolve().parent)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"无法打开数据目录：{exc}") from exc
        return {"opened": True}

    @application.get("/api/settings/amap")
    def amap_settings_status() -> dict[str, object]:
        provider = current_provider()
        return {
            "storage": (
                "windows_current_user" if credential_store is not None else "environment"
            ),
            "web_service_configured": provider.configured,
            "js_api_configured": bool(runtime_credentials.js_api_key),
            "js_security_configured": bool(runtime_credentials.js_security_key),
        }

    @application.post("/api/settings/amap")
    def save_amap_settings(payload: AmapSettingsUpdate) -> dict[str, object]:
        nonlocal runtime_credentials
        if credential_store is None:
            raise HTTPException(
                status_code=409,
                detail="源码开发模式请继续使用环境变量配置高德；发行包才提供用户级保护存储",
            )
        credentials = AmapCredentials(
            payload.web_service_key,
            payload.js_api_key,
            payload.js_security_key,
        )
        try:
            credential_store.save(credentials)
            loaded = credential_store.load()
        except CredentialStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if loaded is None:
            raise HTTPException(status_code=500, detail="高德配置保存后无法读取")
        runtime_credentials = loaded
        return {
            "saved": True,
            "web_service_configured": True,
            "js_api_configured": True,
            "js_security_configured": True,
        }

    @application.get("/api/map/config")
    def map_config() -> dict[str, object]:
        provider = current_provider()
        browser_key = runtime_credentials.js_api_key
        browser_security_code = runtime_credentials.js_security_key
        return {
            "js_api_enabled": bool(browser_key and browser_security_code),
            "web_service_enabled": provider.configured,
            "js_api_key": browser_key if browser_key and browser_security_code else None,
            "service_host": "/_AMapService",
        }

    @application.get("/_AMapService/{proxy_path:path}", include_in_schema=False)
    def amap_js_proxy(proxy_path: str, request: Request) -> Response:
        browser_security_code = runtime_credentials.js_security_key
        if not browser_security_code:
            raise HTTPException(status_code=503, detail="未配置高德 JS API 安全代理")
        if (
            not proxy_path
            or ".." in proxy_path.split("/")
            or not proxy_path.startswith(("v3/", "v4/", "v5/"))
        ):
            raise HTTPException(status_code=400, detail="不允许的高德代理路径")

        query = [
            (key, value)
            for key, value in parse_qsl(request.url.query, keep_blank_values=True)
            if key.casefold() != "jscode"
        ]
        query.append(("jscode", browser_security_code))
        upstream_host = (
            "https://webapi.amap.com"
            if proxy_path.startswith("v4/map/styles")
            else "https://restapi.amap.com"
        )
        upstream_url = f"{upstream_host}/{proxy_path}?{urlencode(query)}"
        upstream_request = UrlRequest(
            upstream_url,
            headers={"Accept": request.headers.get("accept", "*/*")},
        )
        try:
            with urlopen(upstream_request, timeout=8.0) as upstream_response:
                content = upstream_response.read()
                content_type = upstream_response.headers.get(
                    "Content-Type", "application/octet-stream"
                )
                return Response(
                    content=content,
                    status_code=upstream_response.status,
                    media_type=content_type.split(";", maxsplit=1)[0],
                )
        except HTTPError as exc:
            content_type = exc.headers.get("Content-Type", "application/json")
            return Response(
                content=exc.read(),
                status_code=exc.code,
                media_type=content_type.split(";", maxsplit=1)[0],
            )
        except URLError as exc:
            raise HTTPException(status_code=502, detail="高德 JS API 代理连接失败") from exc

    @application.get("/api/restaurants")
    def list_restaurants() -> list[dict[str, object]]:
        try:
            return load_restaurants(restaurant_path)
        except RestaurantDataError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @application.post("/api/dianping/parse")
    def parse_dianping_share(payload: DianpingParseRequest) -> dict[str, object]:
        try:
            return asdict(parse_dianping_input(payload.text))
        except DianpingInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.post("/api/data/import")
    def import_restaurant_file(payload: RestaurantImportRequest) -> dict[str, object]:
        try:
            result = import_restaurants_json(
                payload.json_text,
                restaurant_path,
                backup_dir=effective_paths.backup_dir,
            )
            group_ranking_state.invalidate()
            return {
                "imported": True,
                "count": result.count,
                "backup_path": str(result.backup_path.resolve()),
            }
        except RestaurantDataError as exc:
            _raise_mutation_error(exc)

    @application.post(
        "/api/restaurants", status_code=status.HTTP_201_CREATED
    )
    def add_restaurant(payload: RestaurantCreate) -> dict[str, object]:
        try:
            created = create_restaurant(
                name=payload.name,
                restaurant_type=payload.type,
                detail=payload.detail,
                dianping_url=payload.dianping_url,
                path=restaurant_path,
                tags=payload.tags,
            )
            group_ranking_state.invalidate()
            return created
        except RestaurantDataError as exc:
            _raise_mutation_error(exc)

    @application.patch("/api/restaurants/{restaurant_id}")
    def edit_restaurant(
        restaurant_id: int, payload: RestaurantUpdate
    ) -> dict[str, object]:
        try:
            updated = update_restaurant(
                restaurant_id,
                payload.model_dump(exclude_unset=True),
                restaurant_path,
            )
            group_ranking_state.invalidate()
            return updated
        except RestaurantDataError as exc:
            _raise_mutation_error(exc)

    @application.delete("/api/restaurants/{restaurant_id}")
    def remove_restaurant(restaurant_id: int) -> dict[str, object]:
        try:
            deleted = delete_restaurant(restaurant_id, restaurant_path)
            group_ranking_state.invalidate()
            return {"deleted": deleted}
        except RestaurantDataError as exc:
            _raise_mutation_error(exc)

    @application.patch("/api/restaurants/{restaurant_id}/selection-status")
    def change_restaurant_selection_status(
        restaurant_id: int, payload: RestaurantSelectionStatusUpdate
    ) -> dict[str, object]:
        try:
            updated = set_restaurant_selection_status(
                restaurant_id, payload.selection_status, restaurant_path
            )
            group_ranking_state.invalidate()
            return updated
        except RestaurantDataError as exc:
            _raise_mutation_error(exc)

    @application.get("/api/places/search")
    def search_places(q: str) -> dict[str, object]:
        query = q.strip()
        if not query:
            raise HTTPException(status_code=422, detail="搜索关键词不能为空")
        provider = current_provider()
        try:
            candidates = provider.search_places(query)
        except MapProviderError as exc:
            _raise_map_error(exc)
        auto_candidate = choose_auto_candidate(query, candidates)
        return {
            "query": query,
            "auto_eligible": auto_candidate is not None,
            "candidates": [candidate.to_dict() for candidate in candidates],
        }

    @application.get("/api/origins/search")
    def search_origins(q: str) -> dict[str, object]:
        query = q.strip()
        if not query:
            raise HTTPException(status_code=422, detail="出发地关键词不能为空")
        provider = current_provider()
        try:
            candidates = provider.search_origins(query)
        except MapProviderError as exc:
            _raise_map_error(exc)
        return {
            "query": query,
            "candidates": [candidate.to_dict() for candidate in candidates],
        }

    @application.post("/api/restaurants/resolve-locations")
    def resolve_locations() -> dict[str, object]:
        provider = current_provider()
        if not provider.configured:
            _raise_map_error(MapConfigurationError("未配置高德 Web 服务密钥"))
        try:
            results = resolve_pending_restaurants(provider, restaurant_path)
        except (MapProviderError, RestaurantDataError) as exc:
            if isinstance(exc, MapProviderError):
                _raise_map_error(exc)
            _raise_mutation_error(exc)
        group_ranking_state.invalidate()
        return {"results": results}

    @application.patch("/api/restaurants/{restaurant_id}/location")
    def confirm_restaurant_location(
        restaurant_id: int, payload: RestaurantLocationUpdate
    ) -> dict[str, object]:
        try:
            updated = set_restaurant_location(
                restaurant_id,
                address=payload.address,
                longitude=payload.longitude,
                latitude=payload.latitude,
                amap_poi_id=payload.amap_poi_id,
                location_status="manual_confirmed",
                path=restaurant_path,
            )
            group_ranking_state.invalidate()
            return updated
        except RestaurantDataError as exc:
            _raise_mutation_error(exc)

    @application.get("/api/restaurants/{restaurant_id}/nearby-transit")
    def nearby_transit(restaurant_id: int) -> dict[str, object]:
        provider = current_provider()
        try:
            restaurants = load_restaurants(restaurant_path)
        except RestaurantDataError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        restaurant = next(
            (item for item in restaurants if item["id"] == restaurant_id), None
        )
        if restaurant is None:
            raise HTTPException(status_code=404, detail=f"未找到餐厅 id {restaurant_id}")
        if (
            restaurant["location_status"]
            not in {"auto_resolved", "manual_confirmed"}
            or restaurant["longitude"] is None
            or restaurant["latitude"] is None
        ):
            raise HTTPException(status_code=409, detail="餐厅尚未确认位置")
        try:
            stations = provider.nearby_transit(
                restaurant["longitude"], restaurant["latitude"]
            )
        except MapProviderError as exc:
            _raise_map_error(exc)
        return {
            "restaurant_id": restaurant_id,
            "radius_m": 1000,
            "distance_note": "距离为约 1 公里范围内的近似直线距离",
            "stations": [station.to_dict() for station in stations],
        }

    @application.post("/api/random")
    def random_restaurant() -> dict[str, object]:
        try:
            restaurants = load_restaurants(restaurant_path)
            return choose_restaurant(restaurants, randint)
        except EmptyRestaurantListError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RestaurantDataError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @application.post("/api/group/rank")
    def group_rank(payload: GroupRankRequest) -> dict[str, object]:
        provider = current_provider()
        try:
            current_restaurants = load_restaurants(restaurant_path)
        except RestaurantDataError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if not active_restaurants(current_restaurants):
            group_ranking_state.invalidate()
            raise HTTPException(
                status_code=409,
                detail="活跃餐厅名单为空，无法进行多人排名",
            )
        if not provider.configured:
            _raise_map_error(MapConfigurationError("未配置高德 Web 服务密钥"))
        group_ranking_state.invalidate()
        try:
            result = perform_group_ranking(
                [item.model_dump() for item in payload.participants],
                provider,
                restaurant_path,
            )
        except GroupRankingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RestaurantDataError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        ranking_id = group_ranking_state.record(result)
        return {
            **result,
            "ranking_id": ranking_id,
            "random_eligible": ranking_id is not None,
        }

    @application.post("/api/group/random")
    def group_random(payload: GroupRandomRequest) -> dict[str, object]:
        try:
            current_version = load_restaurant_snapshot(restaurant_path).version
            return group_ranking_state.draw(
                payload.ranking_id, current_version, randint
            )
        except GroupRandomUnavailableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RestaurantDataError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return application


app = create_app()
