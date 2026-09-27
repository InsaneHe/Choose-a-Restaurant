"""Runtime paths and first-run data initialization."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.storage import RestaurantDataError, load_restaurants


APP_NAME = "ChooseRestaurant"
APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
TEMPLATE_PATH = APP_DIR / "resources" / "restaurants-template.json"


@dataclass(frozen=True)
class RuntimePaths:
    packaged: bool
    data_dir: Path
    data_path: Path
    backup_dir: Path
    credential_path: Path | None


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def resolve_runtime_paths(
    *,
    packaged: bool | None = None,
    local_appdata: Path | str | None = None,
) -> RuntimePaths:
    frozen = is_packaged() if packaged is None else packaged
    if not frozen:
        data_dir = PROJECT_ROOT / "data"
        return RuntimePaths(False, data_dir, data_dir / "restaurants.json", PROJECT_ROOT / "backups", None)

    appdata_value = local_appdata or os.getenv("LOCALAPPDATA")
    if not appdata_value:
        raise RestaurantDataError("无法确定当前 Windows 用户的 LOCALAPPDATA 目录")
    root = Path(appdata_value).expanduser().resolve() / APP_NAME
    data_dir = root / "data"
    return RuntimePaths(
        True,
        data_dir,
        data_dir / "restaurants.json",
        data_dir / "backups",
        root / "config" / "amap-credentials.dat",
    )


def ensure_first_run_data(
    paths: RuntimePaths, template_path: Path | str = TEMPLATE_PATH
) -> bool:
    """Create packaged user data exactly once; return True when initialized."""

    if paths.data_path.exists():
        load_restaurants(paths.data_path)
        return False
    template = Path(template_path)
    load_restaurants(template)
    raw = template.read_bytes()
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(paths.data_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        load_restaurants(paths.data_path)
        return False
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        paths.data_path.unlink(missing_ok=True)
        raise
    load_restaurants(paths.data_path)
    return True
