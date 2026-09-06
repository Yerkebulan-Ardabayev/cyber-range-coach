from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cyber_range_coach.models import LabRun, LearningSession, LinuxHost
from cyber_range_coach.services.ssh import TerminalLineEditor, TerminalManager


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
    terminal._consume_initialization(terminal.initialization_marker)
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
        assert stored.terminal_input_kinds == ["legacy_unknown", "shell_command"]
        assert stored.input_integrity == "unverified"
        assert stored.input_integrity_reason == "reconnected_run"
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


@pytest.mark.asyncio
async def test_terminal_blocks_input_until_profile_check_and_fails_closed(
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
        )
        host = LinuxHost(
            name="Fresh Linux VM",
            host="192.0.2.52",
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
    initialization_writes = list(connection.process.stdin.values)

    await terminal.input("pwd\n")
    assert connection.process.stdin.values == initialization_writes
    assert terminal.submitted_commands == []

    terminal._consume_initialization(terminal.initialization_failure_marker)
    await terminal.flush()
    with db.session_factory() as session:
        stored = session.get(LabRun, run_id)
        assert stored is not None
        assert stored.input_integrity == "unverified"
        assert stored.input_integrity_reason == "temporary_profile_mismatch"

    await manager.stop(run_id)


@pytest.mark.parametrize(
    ("input_data", "expected"),
    [
        ("pwX\x15pwd\r", "pwd"),
        ("pd\x1b[D\x1b[C\x1b[Dw\r", "pwd"),
        ("xpwd\x01\x1b[3~\x05\r", "pwd"),
        ("pwdX\x1b[D\x0b\r", "pwd"),
        ("pwX\x7fd\r", "pwd"),
        ("wrong\x03pwd\r", "pwd"),
    ],
)
def test_terminal_line_editor_matches_supported_emacs_editing(
    input_data: str, expected: str
) -> None:
    editor = TerminalLineEditor()
    assert editor.feed(input_data) == [expected]
    assert editor.integrity == "verified"


def test_terminal_line_editor_keeps_split_escape_and_fails_closed_on_unknown_input() -> None:
    editor = TerminalLineEditor()
    assert editor.feed("pd\x1b[") == []
    assert editor.feed("Dw\r") == ["pwd"]
    assert editor.integrity == "verified"

    editor = TerminalLineEditor()
    editor.feed("pw\t")
    assert editor.integrity == "unverified"
    assert editor.reason == "tab_completion"
