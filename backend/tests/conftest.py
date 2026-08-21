from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cyber_range_coach.app import create_app
from cyber_range_coach.config import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'academy.db').as_posix()}",
        curriculum_dir=ROOT / "curriculum",
        frontend_dist=tmp_path / "frontend-dist",
        testing=True,
        allow_test_role_header=True,
        allow_insecure_dev_secrets=True,
        relay_port_start=49300,
        relay_port_end=49320,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        test_client.get("/api/v2/devices/me")
        csrf = test_client.cookies.get("crc_csrf")
        if csrf:
            test_client.headers.update({"x-csrf-token": csrf})
        yield test_client


def csrf_headers(role: str) -> dict[str, str]:
    return {"x-test-role": role, "x-csrf-token": "test-csrf"}
