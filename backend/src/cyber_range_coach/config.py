from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[3]


def default_data_dir() -> Path:
    override = os.environ.get("CRC_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_path("CyberRangeCoach", appauthor=False, ensure_exists=False))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRC_", extra="ignore")

    environment: str = "production"
    data_dir: Path = Field(default_factory=default_data_dir)
    database_url: str | None = None
    curriculum_dir: Path = Field(default_factory=lambda: project_root() / "curriculum")
    frontend_dist: Path = Field(default_factory=lambda: project_root() / "frontend" / "dist")
    bind_host: str = "127.0.0.1"
    port: int = 8443
    lan_mode: bool = False
    tls_enabled: bool = False
    relay_bind_host: str = "0.0.0.0"
    relay_advertised_host: str | None = None
    relay_port_start: int = 47000
    relay_port_end: int = 47100
    relay_ttl_seconds: int = 2 * 60 * 60
    subprocess_timeout_seconds: float = 8.0
    ssh_connect_timeout_seconds: float = 8.0
    terminal_reconnect_grace_seconds: float = 30.0
    max_transcript_bytes: int = 262_144
    max_import_bytes: int = 25 * 1024 * 1024
    pairing_ttl_seconds: int = 600
    session_cookie_name: str = "crc_session"
    csrf_cookie_name: str = "crc_csrf"
    testing: bool = False
    allow_test_role_header: bool = False
    allow_insecure_dev_secrets: bool = False
    external_ai_enabled: bool = False

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'data' / 'academy.db').as_posix()}"

    @property
    def imports_dir(self) -> Path:
        return self.data_dir / "imports"

    @property
    def certificates_dir(self) -> Path:
        return self.data_dir / "certificates"

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def published_content_dir(self) -> Path:
        return self.data_dir / "content"

    def ensure_directories(self) -> None:
        for directory in (
            self.data_dir / "data",
            self.imports_dir,
            self.data_dir / "backups",
            self.logs_dir,
            self.certificates_dir,
            self.runtime_dir,
            self.published_content_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
