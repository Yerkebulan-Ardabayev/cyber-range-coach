from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace

import pytest

from cyber_range_coach.models import LinuxHost
from cyber_range_coach.services import wsl
from cyber_range_coach.services.commands import CommandResult
from cyber_range_coach.services.relay import RelayManager


class FakeRunner:
    def __init__(self, address: str) -> None:
        self.address = address

    async def run(self, _executable: str, *args: str, **_kwargs: object) -> CommandResult:
        if "--exec" in args:
            return CommandResult(("wsl.exe",), 0, f"{self.address}\n", "")
        return CommandResult(("wsl.exe",), 0, "Ubuntu\n", "")


def _add_host(client, host: str = "127.0.0.1", relay_source_ip: str = "172.30.164.100") -> LinuxHost:
    with client.app.state.db.session_factory() as session:
        linux = LinuxHost(
            name="WSL Ubuntu", host=host, port=22, relay_source_ip=relay_source_ip,
            username="student", runner_username="range-runner",
            encrypted_private_key="test", public_key="test",
            encrypted_runner_private_key="test", runner_public_key="test",
        )
        session.add(linux)
        session.commit()
        session.refresh(linux)
        session.expunge(linux)
        return linux


def _stored(client) -> str | None:
    with client.app.state.db.session_factory() as session:
        return session.query(LinuxHost).one().relay_source_ip


@pytest.mark.asyncio
async def test_new_wsl_address_after_reboot_is_used_and_saved(client, monkeypatch) -> None:
    monkeypatch.setattr(wsl, "sys", SimpleNamespace(platform="win32"))
    host = _add_host(client)
    source = await wsl.relay_source_ip_for_start(client.app.state.db, FakeRunner("172.27.80.5"), 8, host)
    assert source == "172.27.80.5"
    assert _stored(client) == "172.27.80.5"


@pytest.mark.asyncio
async def test_public_wsl_answer_is_ignored(client, monkeypatch) -> None:
    monkeypatch.setattr(wsl, "sys", SimpleNamespace(platform="win32"))
    host = _add_host(client)
    source = await wsl.relay_source_ip_for_start(client.app.state.db, FakeRunner("8.8.8.8"), 8, host)
    assert source == "172.30.164.100"
    assert _stored(client) == "172.30.164.100"


@pytest.mark.asyncio
async def test_non_wsl_vm_keeps_configured_address(client, monkeypatch) -> None:
    monkeypatch.setattr(wsl, "sys", SimpleNamespace(platform="win32"))
    host = _add_host(client, host="192.168.10.50", relay_source_ip="192.168.10.50")
    source = await wsl.relay_source_ip_for_start(client.app.state.db, FakeRunner("172.27.80.5"), 8, host)
    assert source == "192.168.10.50"
    assert _stored(client) == "192.168.10.50"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.asyncio
async def test_active_relay_for_old_wsl_address_is_replaced() -> None:
    port = _free_port()
    manager = RelayManager("127.0.0.1", port, port, ttl_seconds=60)
    first = await manager.start(1, "127.0.0.1", 9, "172.30.164.100")
    second = await manager.start(1, "127.0.0.1", 9, "172.27.80.5")
    try:
        assert second is not first
        assert second.allowed_source_ip == "172.27.80.5"
        assert manager.get(1) is second
        assert not first.server.is_serving()
        same = await manager.start(1, "127.0.0.1", 9, "172.27.80.5")
        assert same is second
    finally:
        await manager.stop_all()
        await asyncio.sleep(0)


def test_relay_start_endpoint_uses_live_wsl_address(client, monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from cyber_range_coach.models import TargetProfile

    monkeypatch.setattr(wsl, "sys", SimpleNamespace(platform="win32"))
    _add_host(client)
    with client.app.state.db.session_factory() as session:
        target = TargetProfile(
            display_name="Juice Shop", container_reference="juice", container_port=3000,
            image_digest="sha256:test", host_endpoint="http://127.0.0.1:3000", fingerprint="f" * 64,
        )
        session.add(target)
        session.commit()
        target_id = target.id
    client.app.state.runner = FakeRunner("172.27.80.5")
    client.app.state.range_runner.relay = AsyncMock(return_value={"reachable": True})
    response = client.post(
        f"/api/v2/targets/{target_id}/relay/start",
        json={"linux_vm_ip": "172.27.80.5"},
        headers={"x-test-role": "owner"},
    )
    try:
        assert response.status_code == 200, response.text
        assert response.json()["allowed_source_ip"] == "172.27.80.5"
        assert _stored(client) == "172.27.80.5"
        stale = client.post(
            f"/api/v2/targets/{target_id}/relay/start",
            json={"linux_vm_ip": "172.30.164.100"},
            headers={"x-test-role": "owner"},
        )
        assert stale.status_code == 409
    finally:
        client.post(f"/api/v2/targets/{target_id}/relay/stop", headers={"x-test-role": "owner"})


def test_lesson_start_after_reboot_opens_relay_for_live_wsl_address(client, monkeypatch) -> None:
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from cyber_range_coach.models import TargetProfile
    from cyber_range_coach.routers import learning
    from cyber_range_coach.schemas import TargetVerifyResponse
    from cyber_range_coach.services.preflight import REQUIRED_LEARNING_TOOLS

    monkeypatch.setattr(wsl, "sys", SimpleNamespace(platform="win32"))
    with client.app.state.db.session_factory() as session:
        session.add(
            LinuxHost(
                name="WSL Ubuntu", host="127.0.0.1", port=22, relay_source_ip="172.30.164.100",
                username="student", runner_username="range-runner",
                encrypted_private_key="test", public_key="test",
                encrypted_runner_private_key="test", runner_public_key="test",
                host_key="ssh-ed25519 test", host_key_fingerprint="SHA256:test",
                confirmed_at=datetime.now(UTC),
            )
        )
        target = TargetProfile(
            display_name="Juice Shop", container_reference="juice", container_port=3000,
            image_digest="sha256:test", host_endpoint="http://127.0.0.1:3000", fingerprint="f" * 64,
            allowed_curriculum_tags=["web"],
        )
        session.add(target)
        session.commit()
        target_id = target.id
    created = client.post(
        "/api/v2/sessions",
        json={"duration_minutes": 15, "lesson_ids": ["tcp-reachability"]},
        headers={"x-test-role": "operator"},
    )
    assert created.status_code == 201, created.text
    client.app.state.runner = FakeRunner("172.27.80.5")
    client.app.state.terminals.verify_student_boundary = AsyncMock(return_value={"safe": True})
    client.app.state.range_runner.tools = AsyncMock(
        return_value={
            "protocol": "crc-range-check/v1",
            "check": "tools",
            "tools": {tool: True for tool in REQUIRED_LEARNING_TOOLS},
        }
    )
    client.app.state.range_runner.relay = AsyncMock(return_value={"reachable": True})
    monkeypatch.setattr(
        learning,
        "verify_target",
        AsyncMock(
            return_value=TargetVerifyResponse(
                target_id=target_id, reachable=True, tcp_connected=True,
                http_response_received=True, detail="ok", checked_at=datetime.now(UTC),
            )
        ),
    )
    response = client.post(
        "/api/v2/lab-runs",
        json={
            "session_id": created.json()["id"],
            "lesson_id": "tcp-reachability",
            "target_id": target_id,
            "prediction": "Ожидаю, что порт открыт",
        },
        headers={"x-test-role": "operator"},
    )
    try:
        assert response.status_code == 201, response.text
        assert client.app.state.relays.get(target_id).allowed_source_ip == "172.27.80.5"
        assert _stored(client) == "172.27.80.5"
    finally:
        client.post(f"/api/v2/targets/{target_id}/relay/stop", headers={"x-test-role": "owner"})
