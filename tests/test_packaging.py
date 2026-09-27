import json
import os
import secrets
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.credentials import AmapCredentials, WindowsCredentialStore
from app.launcher import PortInUseError, ensure_port_available, run
from app.main import (
    AmapSettingsUpdate,
    RestaurantImportRequest,
    create_app,
)
from app.runtime import (
    PROJECT_ROOT,
    TEMPLATE_PATH,
    RuntimePaths,
    ensure_first_run_data,
    resolve_runtime_paths,
)
from app.storage import RestaurantDataError, load_restaurants


def endpoint(application: Any, path: str, method: str):
    return next(
        route.endpoint
        for route in application.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.credentials: AmapCredentials | None = None

    def load(self) -> AmapCredentials | None:
        return self.credentials

    def save(self, credentials: AmapCredentials) -> None:
        self.credentials = credentials


class PackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.paths = RuntimePaths(
            True,
            self.root / "data",
            self.root / "data" / "restaurants.json",
            self.root / "data" / "backups",
            self.root / "config" / "amap-credentials.dat",
        )

    def test_distribution_template_matches_published_seventeen(self) -> None:
        restaurants = load_restaurants(TEMPLATE_PATH)

        self.assertEqual(len(restaurants), 17)
        self.assertEqual([item["id"] for item in restaurants], list(range(1, 18)))
        self.assertIn("青鹤谷", {item["name"] for item in restaurants})
        self.assertEqual(
            TEMPLATE_PATH.read_bytes(),
            (PROJECT_ROOT / "data" / "restaurants.json").read_bytes(),
        )

    def test_first_run_initializes_once_and_replacement_never_overwrites(self) -> None:
        self.assertTrue(ensure_first_run_data(self.paths))
        first_bytes = self.paths.data_path.read_bytes()
        records = json.loads(first_bytes.decode("utf-8"))
        records[0]["tags"] = ["个人标签"]
        records[0]["selection_status"] = "archived"
        self.paths.data_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        personalized = self.paths.data_path.read_bytes()

        self.assertFalse(ensure_first_run_data(self.paths))
        self.assertEqual(self.paths.data_path.read_bytes(), personalized)
        self.assertNotEqual(personalized, first_bytes)

    def test_import_backs_up_seventeen_and_restart_keeps_user_state(self) -> None:
        ensure_first_run_data(self.paths)
        original = self.paths.data_path.read_bytes()
        imported = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        imported[0]["tags"] = ["總店", "Personal"]
        imported[0]["selection_status"] = "archived"
        application = create_app(self.paths.data_path, runtime_paths=self.paths)

        result = endpoint(application, "/api/data/import", "POST")(
            RestaurantImportRequest(
                json_text=json.dumps(imported, ensure_ascii=False, indent=2)
            )
        )

        self.assertEqual(result["count"], 17)
        backup_path = Path(result["backup_path"])
        self.assertEqual(backup_path.read_bytes(), original)
        self.assertFalse(ensure_first_run_data(self.paths))
        restarted = load_restaurants(self.paths.data_path)
        self.assertEqual(len(restarted), 17)
        self.assertEqual(restarted[0]["tags"], ["總店", "Personal"])
        self.assertEqual(restarted[0]["selection_status"], "archived")

    def test_invalid_import_does_not_back_up_or_overwrite(self) -> None:
        ensure_first_run_data(self.paths)
        before = self.paths.data_path.read_bytes()
        application = create_app(self.paths.data_path, runtime_paths=self.paths)

        with self.assertRaises(HTTPException):
            endpoint(application, "/api/data/import", "POST")(
                RestaurantImportRequest(json_text="{invalid")
            )

        self.assertEqual(self.paths.data_path.read_bytes(), before)
        self.assertFalse(self.paths.backup_dir.exists())

    def test_packaged_paths_use_local_appdata_and_source_paths_do_not(self) -> None:
        packaged = resolve_runtime_paths(packaged=True, local_appdata=self.root)
        source = resolve_runtime_paths(packaged=False)

        self.assertEqual(
            packaged.data_path,
            self.root.resolve() / "ChooseRestaurant" / "data" / "restaurants.json",
        )
        self.assertTrue(source.data_path.as_posix().endswith("data/restaurants.json"))
        self.assertNotEqual(packaged.data_path, source.data_path)

    def test_configuration_api_reports_status_without_echoing_protected_values(self) -> None:
        ensure_first_run_data(self.paths)
        store = MemoryCredentialStore()
        application = create_app(
            self.paths.data_path,
            credential_store=store,
            runtime_paths=self.paths,
        )
        generated = AmapCredentials(
            "web-" + secrets.token_urlsafe(12),
            "js-" + secrets.token_urlsafe(12),
            "security-" + secrets.token_urlsafe(12),
        )

        saved = endpoint(application, "/api/settings/amap", "POST")(
            AmapSettingsUpdate(**generated.__dict__)
        )
        status = endpoint(application, "/api/settings/amap", "GET")()
        rendered = json.dumps({"saved": saved, "status": status})

        self.assertTrue(all(saved[key] for key in saved if key != "saved"))
        self.assertEqual(status["storage"], "windows_current_user")
        self.assertNotIn(generated.web_service_key, rendered)
        self.assertNotIn(generated.js_api_key, rendered)
        self.assertNotIn(generated.js_security_key, rendered)

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_windows_dpapi_round_trip_is_not_plaintext(self) -> None:
        store = WindowsCredentialStore(self.paths.credential_path)
        credentials = AmapCredentials(
            "web-" + secrets.token_urlsafe(16),
            "js-" + secrets.token_urlsafe(16),
            "security-" + secrets.token_urlsafe(16),
        )

        store.save(credentials)

        protected = self.paths.credential_path.read_bytes()
        self.assertEqual(store.load(), credentials)
        for value in credentials.__dict__.values():
            self.assertNotIn(value.encode("utf-8"), protected)

    def test_port_conflict_is_detected_before_browser_launch(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            listener.listen()
            with self.assertRaisesRegex(PortInUseError, "没有启动浏览器"):
                ensure_port_available("127.0.0.1", port)

    def test_launcher_opens_its_verified_page_and_stops_normally(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        opened: list[str] = []
        stop = threading.Event()

        def browser(url: str) -> None:
            opened.append(url)
            stop.set()

        previous = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(self.root)
        try:
            exit_code = run(
                port=port,
                open_browser=browser,
                browser_enabled=True,
                stop_event=stop,
            )
        finally:
            if previous is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous

        self.assertEqual(exit_code, 0)
        self.assertEqual(opened, [f"http://127.0.0.1:{port}/"])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
            self.assertNotEqual(check.connect_ex(("127.0.0.1", port)), 0)

    def test_static_page_exposes_local_data_and_masked_configuration_controls(self) -> None:
        page = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="runtime-data-path"', page)
        self.assertIn('id="restaurant-import-file"', page)
        self.assertIn('id="amap-web-key" type="password"', page)
        self.assertIn('id="amap-security-key" type="password"', page)
        self.assertIn("window.confirm", script)
        self.assertIn("textContent", script)


if __name__ == "__main__":
    unittest.main()
