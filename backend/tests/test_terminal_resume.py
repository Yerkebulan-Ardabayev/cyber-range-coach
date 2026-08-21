from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cyber_range_coach.models import LabRun, LearningSession, LinuxHost
from cyber_range_coach.services.ssh import TerminalManager


class FakeInput:
    def __init__(self) -> None:
        self.values: list[str] = []

    def write(self, value: str) -> None:
        self.values.append(value)

    async def drain(self) -> None:
        return None


class FakeOutput:
    def __init__(self, closed: asyncio.Event) -> None:
        self.closed = closed

    async def read(self, _size: int) -> str:
        await self.closed.wait()
        return ""


class FakeProcess:
    def __init__(self) -> None:
        self.closed = asyncio.Event()
        self.stdin = FakeInput()
        self.stdout = FakeOutput(self.closed)
        self.exit_status = 0

    def change_terminal_size(self, _columns: int, _rows: int) -> None:
        return None

    def terminate(self) -> None:
        self.closed.set()

    def kill(self) -> None:
        self.closed.set()

    async def wait_closed(self) -> None:
        await self.closed.wait()


class FakeConnection:
    def __init__(self, boundary_json: str = "") -> None:
        self.process = FakeProcess()
        self.boundary_json = boundary_json
        self.commands: list[str] = []

    async def create_process(self, **_kwargs: object) -> FakeProcess:
        return self.process

    async def run(self, command: str, check: bool = False):
        del check
        self.commands.append(command)
        return type(
            "FakeResult",
            (),
            {"stdout": self.boundary_json, "exit_status": 0},
        )()

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_reopened_terminal_preserves_transcript_and_command_ledger(
    client, monkeypatch
) -> None:
    db = client.app.state.db
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=["linux-navigation-pwd"])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id="linux-navigation-pwd",
            skill_id="linux-navigation",
            prediction="Ожидаю путь",
            transcript="student$ pwd\n/home/student\n",
            terminal_inputs=["pwd"],
            terminal_input_offsets=[0],
        )
        host = LinuxHost(
            name="Test Linux VM",
            host="192.0.2.50",
            port=22,
            username="student",
            runner_username="range-runner",
            encrypted_private_key="test",
            public_key="test",
            encrypted_runner_private_key="test",
            runner_public_key="test",
            host_key="ssh-ed25519 test",
            host_key_fingerprint="SHA256:test",
            confirmed_at=datetime.now(UTC),
        )
        session.add_all([run, host])
        session.commit()
        run_id = run.id

    connection = FakeConnection()

    async def fake_connect(*_args: object, **_kwargs: object) -> FakeConnection:
        return connection

    monkeypatch.setattr("cyber_range_coach.services.ssh.asyncssh.connect", fake_connect)
    monkeypatch.setattr(
        "cyber_range_coach.services.ssh.import_private_key", lambda *_args: object()
    )
    manager = TerminalManager(client.app.state.settings, db, object())
    terminal = await manager.get_or_start(run_id)
    assert terminal.buffer == "student$ pwd\n/home/student\n"
    assert terminal.submitted_commands == ["pwd"]

    await terminal.input("id\n")
    terminal._append("uid=1000(student)\n")
    await terminal.flush()
    with db.session_factory() as session:
        stored = session.get(LabRun, run_id)
        assert stored is not None
        assert stored.transcript.endswith("uid=1000(student)\n")
        assert stored.terminal_inputs == ["pwd", "id"]
        assert stored.terminal_input_offsets == [0, len("student$ pwd\n/home/student\n")]
    await manager.stop(run_id)


@pytest.mark.asyncio
async def test_student_boundary_checks_full_noninteractive_sudo_policy(client, monkeypatch) -> None:
    db = client.app.state.db
    with db.session_factory() as session:
        session.add(
            LinuxHost(
                name="Restricted sudo VM",
                host="192.0.2.51",
                port=22,
                username="student",
                runner_username="range-runner",
                encrypted_private_key="test",
                public_key="test",
                encrypted_runner_private_key="test",
                runner_public_key="test",
                host_key="ssh-ed25519 test",
                host_key_fingerprint="SHA256:test",
                confirmed_at=datetime.now(UTC),
            )
        )
        session.commit()
    connection = FakeConnection(
        '{"ssh_authenticated":true,"sudo_access":true,"docker_socket_access":false}'
    )

    async def fake_connect(*_args: object, **_kwargs: object) -> FakeConnection:
        return connection

    monkeypatch.setattr("cyber_range_coach.services.ssh.asyncssh.connect", fake_connect)
    monkeypatch.setattr(
        "cyber_range_coach.services.ssh.import_private_key", lambda *_args: object()
    )
    manager = TerminalManager(client.app.state.settings, db, object())
    result = await manager.verify_student_boundary()
    assert result["safe"] is False
    assert "sudo -n -l" in connection.commands[0]
