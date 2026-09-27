"""Current-user protected storage for AMap configuration on Windows."""

from __future__ import annotations

import ctypes
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


CRYPTPROTECT_UI_FORBIDDEN = 0x1
_DESCRIPTION = "ChooseRestaurant AMap configuration"


class CredentialStoreError(RuntimeError):
    """Raised when protected configuration cannot be read or written."""


@dataclass(frozen=True)
class AmapCredentials:
    web_service_key: str
    js_api_key: str
    js_security_key: str


class CredentialStore(Protocol):
    def load(self) -> AmapCredentials | None: ...

    def save(self, credentials: AmapCredentials) -> None: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    return (
        _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))),
        buffer,
    )


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialStoreError("高德配置的用户级保护存储仅支持 Windows")
    input_blob, input_buffer = _blob(data)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        _DESCRIPTION,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        raise CredentialStoreError(f"无法保护高德配置（Windows 错误 {ctypes.get_last_error()}）")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)
        del input_buffer


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialStoreError("高德配置的用户级保护存储仅支持 Windows")
    input_blob, input_buffer = _blob(data)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        raise CredentialStoreError(f"无法读取高德配置（Windows 错误 {ctypes.get_last_error()}）")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)
        del input_buffer


def _validate(credentials: AmapCredentials) -> AmapCredentials:
    values = {}
    for field, value in asdict(credentials).items():
        if not isinstance(value, str) or not value.strip():
            raise CredentialStoreError("三项高德配置都必须填写")
        normalized = value.strip()
        if len(normalized) > 512 or any(ord(character) < 32 for character in normalized):
            raise CredentialStoreError("高德配置格式无效")
        values[field] = normalized
    return AmapCredentials(**values)


class WindowsCredentialStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(self) -> AmapCredentials | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(_unprotect(self.path.read_bytes()).decode("utf-8"))
            return _validate(AmapCredentials(**payload))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise CredentialStoreError("已保存的高德配置无法读取") from exc

    def save(self, credentials: AmapCredentials) -> None:
        normalized = _validate(credentials)
        protected = _protect(
            json.dumps(asdict(normalized), ensure_ascii=False).encode("utf-8")
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
            )
            temporary_path = Path(name)
            with os.fdopen(descriptor, "wb") as output:
                output.write(protected)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise CredentialStoreError("无法保存高德配置") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
