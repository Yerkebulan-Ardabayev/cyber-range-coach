from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from cyber_range_coach.models import LabRun, LinuxHost
from cyber_range_coach.services.preflight import REQUIRED_LEARNING_TOOLS

from .conftest import csrf_headers


def enable_pairing_preflight(client: TestClient) -> None:
    client.app.state.settings.lan_mode = True
    client.app.state.settings.tls_enabled = True
    client.app.state.preflight.run = AsyncMock(return_value=SimpleNamespace(ready=True))


def test_health_and_curriculum_are_available(client: TestClient) -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    curriculum = client.get("/api/v2/curriculum")
    assert curriculum.status_code == 200
    assert len(curriculum.json()["lessons"]) >= 15


def test_viewer_cannot_create_session_or_target(client: TestClient) -> None:
    client.cookies.set("crc_csrf", "test-csrf")
    session = client.post(
        "/api/v2/sessions",
        headers=csrf_headers("viewer"),
        json={"duration_minutes": 15, "lesson_ids": ["linux-navigation-pwd"]},
    )
    assert session.status_code == 403
    target = client.post(
        "/api/v2/targets",
        headers=csrf_headers("viewer"),
        json={
            "container_id": "a" * 64,
            "container_port": 3000,
            "protocol": "tcp",
            "display_name": "Denied",
            "allowed_curriculum_tags": ["web"],
        },
    )
    assert target.status_code == 403


def test_viewer_cannot_create_a_reference_help_event(client: TestClient) -> None:
    client.cookies.set("crc_csrf", "test-csrf")
    response = client.post(
        "/api/v2/command-techniques/linux-pwd-current-directory/reveal",
        headers=csrf_headers("viewer"),
        json={
            "disclosure_key": "viewer-reference-denied",
            "timezone": "Asia/Almaty",
            "surface": "technique_card",
        },
    )
    assert response.status_code == 403


def test_paired_mutation_requires_csrf(client: TestClient) -> None:
    response = client.post(
        "/api/v2/sessions",
        headers={"x-test-role": "operator", "x-csrf-token": ""},
        json={"duration_minutes": 15, "lesson_ids": ["linux-navigation-pwd"]},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


def test_command_practice_mutation_preserves_role_and_csrf_guards(client: TestClient) -> None:
    client.cookies.set("crc_csrf", "test-csrf")
    payload = {
        "technique_id": "linux-pwd-current-directory",
        "shell": "bash",
        "timezone": "Asia/Almaty",
        "answer": "pwd",
    }
    viewer = client.put(
        "/api/v2/command-practice/attempts/security-attempt-01/draft",
        headers=csrf_headers("viewer"),
        json=payload,
    )
    assert viewer.status_code == 403
    csrf = client.put(
        "/api/v2/command-practice/attempts/security-attempt-02/draft",
        headers={"x-test-role": "operator", "x-csrf-token": ""},
        json=payload,
    )
    assert csrf.status_code == 403
    assert csrf.json()["code"] == "csrf_failed"


def test_mission_mutation_preserves_role_and_csrf_guards(client: TestClient) -> None:
    client.cookies.set("crc_csrf", "test-csrf")
    payload = {
        "mission_id": "magpie-missing-clue",
        "variant_id": "magpie-aurora",
        "artifact": "trace: marker=ORBIT-41",
        "explanation": "Маркер связан с сектором west.",
    }
    viewer = client.put(
        "/api/v2/missions/attempts/mission-security-attempt-01/draft",
        headers=csrf_headers("viewer"),
        json=payload,
    )
    assert viewer.status_code == 403
    csrf = client.put(
        "/api/v2/missions/attempts/mission-security-attempt-02/draft",
        headers={"x-test-role": "operator", "x-csrf-token": ""},
        json=payload,
    )
    assert csrf.status_code == 403
    assert csrf.json()["code"] == "csrf_failed"


def test_pairing_code_requires_complete_https_preflight(client: TestClient) -> None:
    response = client.post("/api/v2/devices/pairing-codes", json={"role": "viewer"})
    assert response.status_code == 409
    assert response.json()["code"] == "pairing_preflight_incomplete"


def test_pairing_token_is_one_time(client: TestClient) -> None:
    enable_pairing_preflight(client)
    created = client.post("/api/v2/devices/pairing-codes", json={"role": "viewer"})
    assert created.status_code == 201
    payload = created.json()
    request = {
        "token": payload["token"],
        "device_name": "Test phone",
        "confirmed_fingerprint": payload["certificate_fingerprint"],
    }
    first = client.post("/api/v2/devices/pair", json=request)
    second = client.post("/api/v2/devices/pair", json=request)
    assert first.status_code == 200
    assert second.status_code == 410


@pytest.mark.asyncio
async def test_pairing_token_is_atomic_under_concurrency(client: TestClient) -> None:
    enable_pairing_preflight(client)
    created = client.post("/api/v2/devices/pairing-codes", json={"role": "viewer"})
    payload = created.json()
    request = {
        "token": payload["token"],
        "device_name": "Concurrent phone",
        "confirmed_fingerprint": payload["certificate_fingerprint"],
    }
    transport = httpx.ASGITransport(app=client.app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as first,
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as second,
    ):
        responses = await asyncio.gather(
            first.post("/api/v2/devices/pair", json=request),
            second.post("/api/v2/devices/pair", json=request),
        )
    assert sorted(response.status_code for response in responses) == [200, 410]


@pytest.mark.asyncio
async def test_only_one_lab_run_can_become_active_under_concurrency(
    client: TestClient,
) -> None:
    created_session = client.post(
        "/api/v2/sessions",
        json={"duration_minutes": 15, "lesson_ids": ["linux-navigation-pwd"]},
    )
    assert created_session.status_code == 201
    with client.app.state.db.session_factory() as session:
        session.add(
            LinuxHost(
                name="Test Linux VM",
                host="192.0.2.25",
                port=22,
                username="student",
                runner_username="range-runner",
                encrypted_private_key="test",
                public_key="test",
                encrypted_runner_private_key="test",
                runner_public_key="test",
                host_key="test",
                host_key_fingerprint="SHA256:test",
                confirmed_at=datetime.now(UTC),
            )
        )
        session.commit()
    client.app.state.terminals.verify_student_boundary = AsyncMock(return_value={"safe": True})
    client.app.state.range_runner.tools = AsyncMock(
        return_value={
            "protocol": "crc-range-check/v1",
            "check": "tools",
            "tools": {tool: True for tool in REQUIRED_LEARNING_TOOLS},
        }
    )
    payload = {
        "session_id": created_session.json()["id"],
        "lesson_id": "linux-navigation-pwd",
        "prediction": "Ожидаю абсолютный путь",
    }
    transport = httpx.ASGITransport(app=client.app)
    headers = csrf_headers("operator")
    cookies = {"crc_csrf": "test-csrf"}
    async with (
        httpx.AsyncClient(
            transport=transport,
            base_url="https://testserver",
            headers=headers,
            cookies=cookies,
        ) as first,
        httpx.AsyncClient(
            transport=transport,
            base_url="https://testserver",
            headers=headers,
            cookies=cookies,
        ) as second,
    ):
        responses = await asyncio.gather(
            first.post("/api/v2/lab-runs", json=payload),
            second.post("/api/v2/lab-runs", json=payload),
        )
    assert sorted(response.status_code for response in responses) == [201, 409]
    with client.app.state.db.session_factory() as session:
        active_count = session.scalar(
            select(func.count()).select_from(LabRun).where(LabRun.status == "active")
        )
    assert active_count == 1


def test_lab_start_fails_closed_when_course_tool_is_missing(client: TestClient) -> None:
    created_session = client.post(
        "/api/v2/sessions",
        json={"duration_minutes": 15, "lesson_ids": ["linux-navigation-pwd"]},
    )
    with client.app.state.db.session_factory() as session:
        session.add(
            LinuxHost(
                name="Test Linux VM",
                host="192.0.2.25",
                port=22,
                username="student",
                runner_username="range-runner",
                encrypted_private_key="test",
                public_key="test",
                encrypted_runner_private_key="test",
                runner_public_key="test",
                host_key="test",
                host_key_fingerprint="SHA256:test",
                confirmed_at=datetime.now(UTC),
            )
        )
        session.commit()
    client.app.state.terminals.verify_student_boundary = AsyncMock(return_value={"safe": True})
    client.app.state.range_runner.tools = AsyncMock(
        return_value={
            "protocol": "crc-range-check/v1",
            "check": "tools",
            "tools": {"curl": True},
        }
    )
    response = client.post(
        "/api/v2/lab-runs",
        json={
            "session_id": created_session.json()["id"],
            "lesson_id": "linux-navigation-pwd",
            "prediction": "Ожидаю абсолютный путь",
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "linux_tools_missing"
    assert "nmap" in response.json()["details"]["missing_tools"]


def test_pairing_rejects_unverified_certificate_fingerprint(client: TestClient) -> None:
    enable_pairing_preflight(client)
    created = client.post("/api/v2/devices/pairing-codes", json={"role": "viewer"})
    payload = created.json()
    response = client.post(
        "/api/v2/devices/pair",
        json={
            "token": payload["token"],
            "device_name": "Unverified phone",
            "confirmed_fingerprint": "wrong fingerprint",
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "certificate_fingerprint_mismatch"


def test_terminal_denies_viewer_and_cross_origin_operator(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as viewer:
        with client.websocket_connect(
            "/api/v2/terminal/1",
            headers={"x-test-role": "viewer", "origin": "http://testserver"},
        ):
            pass
    assert viewer.value.code == 4403

    with pytest.raises(WebSocketDisconnect) as cross_origin:
        with client.websocket_connect(
            "/api/v2/terminal/1",
            headers={"x-test-role": "operator", "origin": "https://attacker.invalid"},
        ):
            pass
    assert cross_origin.value.code == 4403
