from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Protocol, cast

from cryptography.fernet import Fernet, InvalidToken


class SecretProtectionError(RuntimeError):
    pass


class SecretProtector(Protocol):
    def protect(self, value: bytes) -> str: ...

    def unprotect(self, value: str) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return (
        _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))),
        buffer,
    )


class DPAPIProtector:
    prefix = "dpapi:"
    cryptprotect_ui_forbidden = 0x1

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise SecretProtectionError("Windows DPAPI is unavailable on this platform")
        windll = cast(Any, ctypes).windll
        self.crypt32: Any = windll.crypt32
        self.kernel32: Any = windll.kernel32

    def protect(self, value: bytes) -> str:
        input_blob, input_buffer = _blob(value)
        output_blob = _DataBlob()
        ok = self.crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "Cyber Range Coach secret",
            None,
            None,
            None,
            self.cryptprotect_ui_forbidden,
            ctypes.byref(output_blob),
        )
        # Keep the backing buffer alive until Windows has consumed DATA_BLOB.
        del input_buffer
        if not ok:
            raise SecretProtectionError("CryptProtectData failed")
        try:
            encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self.kernel32.LocalFree(output_blob.pbData)
        return self.prefix + base64.urlsafe_b64encode(encrypted).decode("ascii")

    def unprotect(self, value: str) -> bytes:
        if not value.startswith(self.prefix):
            raise SecretProtectionError("Unexpected secret format")
        encrypted = base64.urlsafe_b64decode(value.removeprefix(self.prefix).encode("ascii"))
        input_blob, input_buffer = _blob(encrypted)
        output_blob = _DataBlob()
        ok = self.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            self.cryptprotect_ui_forbidden,
            ctypes.byref(output_blob),
        )
        # Keep the backing buffer alive until Windows has consumed DATA_BLOB.
        del input_buffer
        if not ok:
            raise SecretProtectionError("CryptUnprotectData failed")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self.kernel32.LocalFree(output_blob.pbData)


class DevelopmentProtector:
    prefix = "dev-fernet:"

    def __init__(self, key_path: Path):
        self.key_path = key_path
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            key_path.write_bytes(key)
            os.chmod(key_path, 0o600)
        self.fernet = Fernet(key)

    def protect(self, value: bytes) -> str:
        return self.prefix + self.fernet.encrypt(value).decode("ascii")

    def unprotect(self, value: str) -> bytes:
        if not value.startswith(self.prefix):
            raise SecretProtectionError("Unexpected development secret format")
        try:
            return self.fernet.decrypt(value.removeprefix(self.prefix).encode("ascii"))
        except InvalidToken as exc:
            raise SecretProtectionError("Development secret cannot be decrypted") from exc


def build_secret_protector(data_dir: Path, allow_insecure_dev: bool) -> SecretProtector:
    if sys.platform == "win32":
        return DPAPIProtector()
    if allow_insecure_dev:
        return DevelopmentProtector(data_dir / "runtime" / ".dev-secret-key")
    raise SecretProtectionError("Secret storage is disabled outside Windows production")
