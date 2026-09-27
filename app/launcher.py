"""Windows console launcher for the one-folder distribution."""

from __future__ import annotations

import argparse
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable

import uvicorn

from app.credentials import WindowsCredentialStore
from app.main import create_app
from app.runtime import ensure_first_run_data, resolve_runtime_paths


HOST = "127.0.0.1"
DEFAULT_PORT = 8000


class PortInUseError(RuntimeError):
    """Raised before startup when the configured local port is unavailable."""


def ensure_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise PortInUseError(
                f"ERROR: port {port} is already in use. "
                "端口已被占用；为避免打开其他程序的网页，本应用没有启动浏览器。"
            ) from exc


def wait_until_ready(url: str, token: str, timeout_seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}api/health", timeout=0.5) as response:
                body = response.read().decode("utf-8")
                if response.status == 200 and token in body:
                    return True
        except (OSError, UnicodeDecodeError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    return False


def run(
    *,
    port: int = DEFAULT_PORT,
    open_browser: Callable[[str], object] = webbrowser.open,
    browser_enabled: bool = True,
    stop_event: threading.Event | None = None,
) -> int:
    try:
        ensure_port_available(HOST, port)
        paths = resolve_runtime_paths(packaged=True)
        initialized = ensure_first_run_data(paths)
        credentials = WindowsCredentialStore(paths.credential_path)  # type: ignore[arg-type]
    except (OSError, RuntimeError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 2

    token = secrets.token_urlsafe(24)
    application = create_app(
        paths.data_path,
        credential_store=credentials,
        runtime_paths=paths,
        health_token=token,
    )
    url = f"http://{HOST}:{port}/"
    config = uvicorn.Config(
        application,
        host=HOST,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="local-web-server", daemon=True)
    thread.start()
    if not wait_until_ready(url, token):
        server.should_exit = True
        thread.join(timeout=5)
        print("启动失败：本地服务未能通过本程序专用的就绪检查；未打开浏览器。", file=sys.stderr)
        return 3

    print("餐厅选择器已启动。关闭此窗口或按 Ctrl+C 即可停止服务。")
    print(f"本地网址：{url}")
    print(f"餐厅数据：{paths.data_path}")
    if initialized:
        print("已从 V2 发行模板初始化 17 家餐厅；以后启动不会覆盖此文件。")
    if browser_enabled:
        open_browser(url)
    try:
        while thread.is_alive():
            if stop_event is not None and stop_event.is_set():
                server.should_exit = True
            thread.join(timeout=0.25)
    except KeyboardInterrupt:
        print("正在停止本地服务……")
        server.should_exit = True
        thread.join(timeout=10)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ChooseRestaurant local launcher")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=argparse.SUPPRESS)
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    exit_code = run(port=arguments.port, browser_enabled=not arguments.no_browser)
    if exit_code and not arguments.no_pause:
        try:
            input("启动失败。按 Enter 关闭窗口 / Press Enter to close...")
        except (EOFError, OSError):
            pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
