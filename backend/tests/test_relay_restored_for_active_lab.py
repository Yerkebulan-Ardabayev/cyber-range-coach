"""Owner's laptop 26.09.2026: after an academy restart the active lab still
looked ready, but its relay was gone and `nc` to the relay port hung."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cyber_range_coach.errors import AppError
from cyber_range_coach.models import LabRun, LearningSession, LinuxHost, TargetProfile
from cyber_range_coach.routers.learning import ensure_run_relay
from cyber_range_coach.services.relay import RelayManager


def _active_run_with_relay(client, relay_port: int, status: str = "active") -> tuple[int, int]:
    settings = client.app.state.settings
    settings.relay_advertised_host = "127.0.0.1"
    with client.app.state.db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=["tcp-reachability"])
        target = TargetProfile(
            display_name="Juice Shop", container_reference="juice", container_port=3000,
            image_digest="sha256:test", host_endpoint="http://127.0.0.1:3000", fingerprint="f" * 64,
        )
        host = LinuxHost(
            name="Linux VM", host="10.20.30.40", port=22, relay_source_ip="10.20.30.40",
            username="student", runner_username="range-runner",
            encrypted_private_key="test", public_key="test",
            encrypted_runner_private_key="test", runner_public_key="test",
            host_key="ssh-ed25519 test", host_key_fingerprint="SHA256:test",
            confirmed_at=datetime.now(UTC),
        )
        session.add_all([learning, target, host])
        session.flush()
        run = LabRun(
            session_id=learning.id, lesson_id="tcp-reachability", skill_id="tcp-reachability",
            target_id=target.id, prediction="Порт открыт", relay_port=relay_port, status=status,
        )
        session.add(run)
        session.commit()
        return run.id, target.id


async def test_restart_brings_back_the_relay_on_the_recorded_port(client) -> None:
    relays = client.app.state.relays
    port = relays.port_start + 7
    run_id, target_id = _active_run_with_relay(client, port)
    assert relays.get(target_id) is None, "fresh academy: relays live only in memory"
    try:
        await ensure_run_relay(SimpleNamespace(app=client.app), run_id)
        handle = relays.get(target_id)
        assert handle is not None and handle.port == port
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        await ensure_run_relay(SimpleNamespace(app=client.app), run_id)
        assert relays.get(target_id) is handle, "a live relay is reused, not restarted"
    finally:
        await relays.stop_all()


async def test_finished_lab_gets_no_relay(client) -> None:
    relays = client.app.state.relays
    run_id, target_id = _active_run_with_relay(client, relays.port_start + 8, status="completed")
    await ensure_run_relay(SimpleNamespace(app=client.app), run_id)
    assert relays.get(target_id) is None


async def test_busy_recorded_port_is_reported_not_moved() -> None:
    relays = RelayManager("127.0.0.1", 47050, 47060, 60)
    blocker = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", 47055)
    try:
        with pytest.raises(AppError) as error:
            await relays.start(1, "127.0.0.1", 3000, "10.20.30.40", port=47055)
        assert error.value.code == "relay_port_busy"
    finally:
        blocker.close()
        await blocker.wait_closed()
        await relays.stop_all()


def test_opening_the_terminal_restores_the_relay_and_reports_failure(client, monkeypatch) -> None:
    from cyber_range_coach.routers import terminal

    calls: list[int] = []

    async def failing_restore(_connection, run_id: int) -> None:
        calls.append(run_id)
        raise AppError(503, "relay_port_busy", "Порт relay этой лабы занят.")

    monkeypatch.setattr(terminal, "ensure_run_relay", failing_restore)
    with client.websocket_connect(
        "/api/v2/terminal/5",
        headers={"x-test-role": "operator", "origin": "http://testserver"},
    ) as socket:
        first = socket.receive_json()
    assert calls == [5]
    assert first["type"] == "error"
    assert "Связь с учебной целью не восстановлена" in first["message"]


def test_grading_restores_the_relay_first(client, monkeypatch) -> None:
    from cyber_range_coach.routers import learning

    async def restore(_connection, run_id: int) -> None:
        raise AppError(418, "restore_called", f"restore {run_id}")

    monkeypatch.setattr(learning, "ensure_run_relay", restore)
    response = client.post("/api/v2/lab-runs/9/grade", headers={"x-test-role": "operator"})
    assert response.status_code == 418, response.text
