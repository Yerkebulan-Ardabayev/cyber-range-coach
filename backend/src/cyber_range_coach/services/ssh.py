from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

import asyncssh
from fastapi import WebSocket

from ..config import Settings
from ..database import Database
from ..errors import AppError
from ..models import LabRun, LinuxHost
from ..schemas import LinuxProbeResponse
from .network import tcp_connect
from .secrets import SecretProtector

LinuxWaker = Callable[[LinuxHost], Awaitable[None]]


async def _no_wake(_host: LinuxHost) -> None:
    return None


# Probe prefers the key the owner is told to compare (ssh_host_ed25519_key.pub);
# asyncssh's default order picked RSA on Ubuntu 24.04 (owner's laptop, 25.09.2026).
PROBE_HOST_KEY_ALGS = (
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "rsa-sha2-512",
    "rsa-sha2-256",
)
HOST_KEY_FILES = {
    "ssh-ed25519": "/etc/ssh/ssh_host_ed25519_key.pub",
    "ssh-rsa": "/etc/ssh/ssh_host_rsa_key.pub",
    "rsa-sha2-256": "/etc/ssh/ssh_host_rsa_key.pub",
    "rsa-sha2-512": "/etc/ssh/ssh_host_rsa_key.pub",
}


def host_key_check_command(algorithm: str) -> str:
    path = HOST_KEY_FILES.get(algorithm)
    if path is None and algorithm.startswith("ecdsa-"):
        path = "/etc/ssh/ssh_host_ecdsa_key.pub"
    return f"ssh-keygen -lf {path or '/etc/ssh/ssh_host_*_key.pub'}"


def create_linux_host_keypair(protector: SecretProtector) -> tuple[str, str]:
    key = asyncssh.generate_private_key("ssh-ed25519")
    private_bytes = key.export_private_key(format_name="openssh")
    public_bytes = key.export_public_key(format_name="openssh")
    if not isinstance(private_bytes, bytes) or not isinstance(public_bytes, bytes):
        raise RuntimeError("AsyncSSH returned an unexpected key format")
    return protector.protect(private_bytes), public_bytes.decode("utf-8").strip()


def import_private_key(host: LinuxHost, protector: SecretProtector) -> asyncssh.SSHKey:
    return asyncssh.import_private_key(protector.unprotect(host.encrypted_private_key))


def import_runner_private_key(host: LinuxHost, protector: SecretProtector) -> asyncssh.SSHKey:
    return asyncssh.import_private_key(protector.unprotect(host.encrypted_runner_private_key))


async def probe_linux_host(
    host: LinuxHost,
    protector: SecretProtector,
    timeout: float,
    waker: LinuxWaker = _no_wake,
) -> LinuxProbeResponse:
    await waker(host)
    reachable, detail = await tcp_connect(host.host, host.port, timeout)
    if not reachable:
        return LinuxProbeResponse(
            host_id=host.id,
            tcp_reachable=False,
            ssh_authenticated=False,
            fingerprint=None,
            host_key=None,
            detail=detail,
        )
    key = import_private_key(host, protector)
    try:
        connection = await asyncio.wait_for(
            asyncssh.connect(
                host.host,
                port=host.port,
                username=host.username,
                client_keys=[key],
                known_hosts=None,
                agent_path=None,
                server_host_key_algs=list(PROBE_HOST_KEY_ALGS),
            ),
            timeout=timeout,
        )
    except (asyncssh.Error, OSError, TimeoutError) as exc:
        return LinuxProbeResponse(
            host_id=host.id,
            tcp_reachable=True,
            ssh_authenticated=False,
            fingerprint=None,
            host_key=None,
            detail=f"TCP 22 доступен, но SSH-аутентификация по ключу не прошла: {type(exc).__name__}",
        )
    try:
        server_key = connection.get_server_host_key()
        if server_key is None:
            raise RuntimeError("SSH server did not expose a host key")
        exported = server_key.export_public_key(format_name="openssh")
        if not isinstance(exported, bytes):
            raise RuntimeError("Unexpected SSH host key format")
        return LinuxProbeResponse(
            host_id=host.id,
            tcp_reachable=True,
            ssh_authenticated=True,
            fingerprint=server_key.get_fingerprint(),
            host_key=exported.decode("utf-8").strip(),
            detail=(
                "SSH-аутентификация по ключу прошла. Сверьте отпечаток "
                f"{server_key.get_algorithm()} с выводом "
                f"`{host_key_check_command(server_key.get_algorithm())}` внутри Linux."
            ),
        )
    finally:
        connection.close()
        await connection.wait_closed()


def write_known_hosts(settings: Settings, host: LinuxHost) -> Path:
    if not host.host_key or not host.host_key_fingerprint or not host.confirmed_at:
        raise AppError(409, "host_key_unconfirmed", "SSH host fingerprint ещё не подтверждён.")
    known_hosts = settings.runtime_dir / f"known-hosts-{host.id}"
    address = host.host if host.port == 22 else f"[{host.host}]:{host.port}"
    known_hosts.write_text(f"{address} {host.host_key}\n", encoding="utf-8")
    os.chmod(known_hosts, 0o600)
    return known_hosts


class RangeRunner:
    """Call the Linux forced-command checker without exposing a general shell."""

    protocol = "crc-range-check/v1"

    def __init__(
        self,
        settings: Settings,
        database: Database,
        protector: SecretProtector | None,
        waker: LinuxWaker = _no_wake,
    ) -> None:
        self.settings = settings
        self.database = database
        self.protector = protector
        self.wake = waker

    def _host(self) -> LinuxHost:
        with self.database.session_factory() as session:
            host = session.query(LinuxHost).order_by(LinuxHost.id).first()
            if host is None or not host.confirmed_at or not host.host_key:
                raise AppError(
                    409,
                    "linux_host_unconfirmed",
                    "Linux VM и SSH fingerprint ещё не подтверждены.",
                )
            session.expunge(host)
            return host

    async def run(self, command: str) -> dict[str, object]:
        parts = command.split(" ")
        relay_command = (
            command.startswith("relay ")
            and command.removeprefix("relay ").isdigit()
            and self.settings.relay_port_start
            <= int(command.removeprefix("relay "))
            <= self.settings.relay_port_end
        )
        nmap_command = (
            len(parts) == 2
            and parts[0] == "nmap"
            and parts[1].isdigit()
            and self.settings.relay_port_start <= int(parts[1]) <= self.settings.relay_port_end
        )
        http_command = (
            len(parts) == 4
            and parts[0] == "http"
            and parts[1].isdigit()
            and self.settings.relay_port_start <= int(parts[1]) <= self.settings.relay_port_end
            and parts[2] in {"http", "https"}
            and 1 <= len(parts[3]) <= 700
            and all(character.isalnum() or character in "-_" for character in parts[3])
        )
        if command != "tools" and not (relay_command or nmap_command or http_command):
            raise AppError(400, "runner_command_denied", "Команда range-runner не разрешена.")
        if self.protector is None:
            raise AppError(503, "secret_storage_unavailable", "SSH secret storage недоступно.")
        host = self._host()
        await self.wake(host)
        known_hosts = write_known_hosts(self.settings, host)
        key = import_runner_private_key(host, self.protector)
        try:
            connection = await asyncio.wait_for(
                asyncssh.connect(
                    host.host,
                    port=host.port,
                    username=host.runner_username,
                    client_keys=[key],
                    known_hosts=str(known_hosts),
                    agent_path=None,
                ),
                timeout=self.settings.ssh_connect_timeout_seconds,
            )
            try:
                result = await asyncio.wait_for(
                    connection.run(command, check=False),
                    timeout=self.settings.ssh_connect_timeout_seconds,
                )
            finally:
                connection.close()
                await connection.wait_closed()
        except (asyncssh.Error, OSError, TimeoutError) as exc:
            raise AppError(
                503,
                "runner_unavailable",
                "Ограниченная проверяющая учётная запись Linux VM недоступна.",
                {"error": type(exc).__name__},
            ) from exc
        if result.exit_status != 0:
            raise AppError(
                409,
                "runner_check_failed",
                "Linux range-runner отклонил проверку.",
                {"exit_status": result.exit_status},
            )
        try:
            payload = json.loads(result.stdout or "")
        except json.JSONDecodeError as exc:
            raise AppError(
                409,
                "runner_protocol_invalid",
                "Linux range-runner вернул неподдерживаемый ответ.",
            ) from exc
        if not isinstance(payload, dict) or payload.get("protocol") != self.protocol:
            raise AppError(
                409,
                "runner_protocol_invalid",
                "Forced-command marker Linux range-runner не подтверждён.",
            )
        return payload

    async def tools(self) -> dict[str, object]:
        return await self.run("tools")

    async def relay(self, port: int) -> dict[str, object]:
        return await self.run(f"relay {port}")

    async def nmap(self, port: int) -> dict[str, object]:
        return await self.run(f"nmap {port}")

    async def http(self, port: int, scheme: str, path: str) -> dict[str, object]:
        encoded_path = base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii").rstrip("=")
        return await self.run(f"http {port} {scheme} {encoded_path}")


class TerminalSession:
    def __init__(
        self,
        run_id: int,
        connection: asyncssh.SSHClientConnection,
        process: Any,
        database: Database,
        max_bytes: int,
        on_finished: Any,
        initial_transcript: str = "",
        initial_commands: list[str] | None = None,
        initial_command_offsets: list[int] | None = None,
        initial_input_kinds: list[str] | None = None,
        initialization_marker: str = "",
        initialization_failure_marker: str = "",
    ) -> None:
        self.run_id = run_id
        self.connection = connection
        self.process = process
        self.database = database
        self.max_bytes = max_bytes
        self.on_finished = on_finished
        self.listeners: set[WebSocket] = set()
        self.buffer = initial_transcript
        self.pending_input = ""
        self.pending_input_start_offset: int | None = None
        self.submitted_commands = list(initial_commands or [])
        self.command_offsets = list(initial_command_offsets or [])
        self.input_kinds = list(initial_input_kinds or [])
        if not self.input_kinds and self.submitted_commands:
            self.input_kinds = ["legacy_unknown"] * len(self.submitted_commands)
        self.history_contaminated = bool(self.submitted_commands)
        self.editor = TerminalLineEditor()
        self.initialization_marker = initialization_marker
        self.initialization_failure_marker = initialization_failure_marker
        self.initialization_buffer = ""
        self.input_ready = not initialization_marker
        self.input_integrity = "verified" if self.input_ready else "initializing"
        self.input_integrity_reason: str | None = None
        self.program_responses_remaining = 0
        self.reader_task = asyncio.create_task(self._read_output())
        self.initialization_task = (
            asyncio.create_task(self._initialization_timeout()) if initialization_marker else None
        )
        self.close_task: asyncio.Task[None] | None = None
        self.closed = False

    async def _read_output(self) -> None:
        try:
            while True:
                chunk = await self.process.stdout.read(4096)
                if not chunk:
                    break
                visible = self._consume_initialization(str(chunk))
                if visible:
                    self._append(visible)
                    await self._broadcast({"type": "output", "data": visible})
        except (asyncssh.Error, OSError):
            await self._broadcast({"type": "error", "message": "Поток SSH-терминала прерван."})
        finally:
            await self.flush()
            await self._broadcast(
                {"type": "exit", "exit_status": self.process.exit_status, "reconnectable": False}
            )
            self.closed = True
            self.connection.close()
            await self.connection.wait_closed()
            self.on_finished(self.run_id)

    def _consume_initialization(self, chunk: str) -> str:
        if self.input_ready or not self.initialization_marker:
            return chunk
        self.initialization_buffer += chunk
        marker_index = self.initialization_buffer.find(self.initialization_marker)
        failure_index = (
            self.initialization_buffer.find(self.initialization_failure_marker)
            if self.initialization_failure_marker
            else -1
        )
        if marker_index < 0 and failure_index < 0:
            self.initialization_buffer = self.initialization_buffer[-16_384:]
            return ""
        profile_verified = marker_index >= 0 and (
            failure_index < 0 or marker_index < failure_index
        )
        matched_index = marker_index if profile_verified else failure_index
        matched_marker = (
            self.initialization_marker
            if profile_verified
            else self.initialization_failure_marker
        )
        visible = self.initialization_buffer[
            matched_index + len(matched_marker) :
        ].lstrip("\r\n")
        self.initialization_buffer = ""
        self.input_ready = True
        self.input_integrity = (
            "verified" if profile_verified and not self.history_contaminated else "unverified"
        )
        self.input_integrity_reason = (
            "reconnected_run"
            if self.history_contaminated
            else (None if profile_verified else "temporary_profile_mismatch")
        )
        if self.initialization_task:
            self.initialization_task.cancel()
            self.initialization_task = None
        self.integrity_broadcast_task = asyncio.create_task(
            self._broadcast(
                {
                    "type": "integrity",
                    "status": self.input_integrity,
                    "message": (
                        "Временный Bash-профиль подтверждён, но продолженный run остаётся незачётным."
                        if self.history_contaminated
                        else (
                            "Временный Bash-профиль и поддерживаемые клавиши подтверждены."
                            if profile_verified
                            else "Фактические Bash bindings не совпали с проверяемым профилем."
                        )
                    ),
                }
            )
        )
        return visible

    async def _initialization_timeout(self) -> None:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            return
        if self.input_ready:
            return
        self.input_ready = True
        self.input_integrity = "unverified"
        self.input_integrity_reason = "temporary_profile_unconfirmed"
        await self._broadcast(
            {
                "type": "integrity",
                "status": "unverified",
                "message": "Профиль ввода не подтверждён. Терминал доступен только для незачётной практики.",
            }
        )

    def _append(self, value: str) -> None:
        combined = self.buffer + value
        encoded = combined.encode("utf-8", errors="replace")
        if len(encoded) > self.max_bytes:
            encoded = encoded[-self.max_bytes :]
            combined = encoded.decode("utf-8", errors="ignore")
            # Existing character offsets no longer refer to the retained tail.
            # Clear the ledger so grading fails closed until a fresh command.
            self.submitted_commands.clear()
            self.command_offsets.clear()
            self.input_kinds.clear()
            self.pending_input = ""
            self.pending_input_start_offset = None
            self.input_integrity = "unverified"
            self.input_integrity_reason = "transcript_truncated"
        self.buffer = combined

    async def _broadcast(self, payload: dict[str, object]) -> None:
        stale: list[WebSocket] = []
        for listener in tuple(self.listeners):
            try:
                await listener.send_json(payload)
            except RuntimeError:
                stale.append(listener)
        for listener in stale:
            self.listeners.discard(listener)

    async def attach(self, websocket: WebSocket) -> None:
        if self.close_task:
            self.close_task.cancel()
            self.close_task = None
        self.listeners.add(websocket)
        if self.buffer:
            await websocket.send_json({"type": "transcript", "data": self.buffer})
        if self.input_ready:
            await websocket.send_json(
                {
                    "type": "ready",
                    "run_id": self.run_id,
                    "input_integrity": self.input_integrity,
                    "integrity_reason": self.input_integrity_reason,
                }
            )
        else:
            await websocket.send_json(
                {"type": "initializing", "message": "Проверяется временный профиль Bash."}
            )

    def detach(self, websocket: WebSocket, grace_seconds: float) -> None:
        self.listeners.discard(websocket)
        if not self.listeners and not self.closed:
            self.close_task = asyncio.create_task(self._close_after_grace(grace_seconds))

    async def _close_after_grace(self, grace_seconds: float) -> None:
        try:
            await asyncio.sleep(grace_seconds)
            await self.close()
        except asyncio.CancelledError:
            return

    async def input(self, data: str) -> None:
        if self.closed:
            raise AppError(409, "terminal_closed", "Сессия терминала закрыта.")
        if not self.input_ready:
            await self._broadcast(
                {"type": "error", "message": "Ввод заблокирован до проверки профиля Bash."}
            )
            return
        self._record_input(data)
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    def _record_input(self, data: str) -> None:
        if self.pending_input_start_offset is None and data:
            self.pending_input_start_offset = len(self.buffer)
        lines = self.editor.feed(data)
        if self.editor.integrity == "unverified":
            self.input_integrity = "unverified"
            self.input_integrity_reason = self.editor.reason
        for line in lines:
            command = line.strip()
            if not command:
                continue
            kind = "program_response" if self.program_responses_remaining else "shell_command"
            if self.program_responses_remaining:
                self.program_responses_remaining -= 1
            else:
                self.program_responses_remaining = command.count("read -r -p")
            self.submitted_commands.append(command[:8000])
            self.command_offsets.append(self.pending_input_start_offset or 0)
            self.input_kinds.append(kind)
            self.submitted_commands = self.submitted_commands[-100:]
            self.command_offsets = self.command_offsets[-100:]
            self.input_kinds = self.input_kinds[-100:]
            self.pending_input_start_offset = None
        self.pending_input = self.editor.text

    def resize(self, columns: int, rows: int) -> None:
        if not self.closed:
            self.process.change_terminal_size(columns, rows)

    async def flush(self) -> None:
        transcript = self.buffer

        def persist() -> None:
            with self.database.session_factory() as session:
                run = session.get(LabRun, self.run_id)
                if run:
                    run.transcript = transcript
                    run.terminal_inputs = list(self.submitted_commands)
                    run.terminal_input_offsets = list(self.command_offsets)
                    run.terminal_input_kinds = list(self.input_kinds)
                    run.input_integrity = self.input_integrity
                    run.input_integrity_reason = self.input_integrity_reason
                    session.commit()

        await asyncio.to_thread(persist)

    async def close(self) -> None:
        if self.closed:
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait_closed(), timeout=3.0)
        except TimeoutError:
            self.process.kill()
        await self.flush()
        self.connection.close()
        await self.connection.wait_closed()
        self.closed = True


class TerminalLineEditor:
    """Limited Emacs-mode line editor used only to verify the executed line."""

    SEQUENCES: ClassVar[dict[str, str]] = {
        "\x1b[D": "left",
        "\x1b[C": "right",
        "\x1b[H": "home",
        "\x1b[F": "end",
        "\x1b[1~": "home",
        "\x1b[4~": "end",
        "\x1b[3~": "delete",
    }

    def __init__(self) -> None:
        self._characters: list[str] = []
        self.cursor = 0
        self.pending_escape = ""
        self.integrity = "verified"
        self.reason: str | None = None

    @property
    def text(self) -> str:
        return "".join(self._characters)

    def _unverified(self, reason: str) -> None:
        self.integrity = "unverified"
        self.reason = self.reason or reason

    def _apply_sequence(self, action: str) -> None:
        if action == "left":
            self.cursor = max(0, self.cursor - 1)
        elif action == "right":
            self.cursor = min(len(self._characters), self.cursor + 1)
        elif action == "home":
            self.cursor = 0
        elif action == "end":
            self.cursor = len(self._characters)
        elif action == "delete" and self.cursor < len(self._characters):
            self._characters.pop(self.cursor)

    def feed(self, data: str) -> list[str]:
        submitted: list[str] = []
        stream = self.pending_escape + data
        self.pending_escape = ""
        index = 0
        newline_count = sum(character in {"\r", "\n"} for character in data)
        if newline_count > 1:
            self._unverified("multiline_paste")
        while index < len(stream):
            character = stream[index]
            if character == "\x1b":
                remaining = stream[index:]
                exact = next(
                    (sequence for sequence in self.SEQUENCES if remaining.startswith(sequence)),
                    None,
                )
                if exact is not None:
                    self._apply_sequence(self.SEQUENCES[exact])
                    index += len(exact)
                    continue
                if any(sequence.startswith(remaining) for sequence in self.SEQUENCES):
                    self.pending_escape = remaining
                    break
                self._unverified("unknown_escape_sequence")
                index += 1
                continue
            if character in {"\r", "\n"}:
                submitted.append(self.text)
                self._characters.clear()
                self.cursor = 0
            elif character in {"\b", "\x7f"}:
                if self.cursor > 0:
                    self.cursor -= 1
                    self._characters.pop(self.cursor)
            elif character == "\x01":
                self.cursor = 0
            elif character == "\x05":
                self.cursor = len(self._characters)
            elif character == "\x15":
                del self._characters[: self.cursor]
                self.cursor = 0
            elif character == "\x0b":
                del self._characters[self.cursor :]
            elif character == "\x03":
                self._characters.clear()
                self.cursor = 0
            elif character == "\t":
                self._unverified("tab_completion")
            elif ord(character) < 32:
                self._unverified("unknown_control_character")
            else:
                self._characters.insert(self.cursor, character)
                self.cursor += 1
                if len(self._characters) > 8000:
                    self._characters = self._characters[-8000:]
                    self.cursor = len(self._characters)
                    self._unverified("input_too_long")
            index += 1
        return submitted


class TerminalManager:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        protector: SecretProtector | None,
        waker: LinuxWaker = _no_wake,
    ) -> None:
        self.settings = settings
        self.database = database
        self.protector = protector
        self.wake = waker
        self.sessions: dict[int, TerminalSession] = {}
        self._lock = asyncio.Lock()

    async def verify_student_boundary(self) -> dict[str, object]:
        if self.protector is None:
            raise AppError(
                503, "secret_storage_unavailable", "SSH secrets недоступны на этом host."
            )
        with self.database.session_factory() as session:
            host = session.query(LinuxHost).order_by(LinuxHost.id).first()
            if host is None:
                raise AppError(409, "linux_host_missing", "Linux VM ещё не настроена.")
            session.expunge(host)
        await self.wake(host)
        known_hosts = write_known_hosts(self.settings, host)
        key = import_private_key(host, self.protector)
        command = (
            "sudo_access=false; docker_socket=false; "
            "if command -v sudo >/dev/null 2>&1 && "
            "{ sudo -n -l >/dev/null 2>&1 || sudo -n true >/dev/null 2>&1; }; "
            "then sudo_access=true; fi; "
            "uid=$(id -u); "
            "for socket in /var/run/docker.sock /run/user/$uid/docker.sock; do "
            'if [ -e "$socket" ] && { [ -r "$socket" ] || [ -w "$socket" ]; }; '
            "then docker_socket=true; fi; done; "
            'printf \'{"ssh_authenticated":true,"sudo_access":%s,'
            '"docker_socket_access":%s}\\n\' "$sudo_access" "$docker_socket"'
        )
        try:
            connection = await asyncio.wait_for(
                asyncssh.connect(
                    host.host,
                    port=host.port,
                    username=host.username,
                    client_keys=[key],
                    known_hosts=str(known_hosts),
                    agent_path=None,
                ),
                timeout=self.settings.ssh_connect_timeout_seconds,
            )
            try:
                result = await asyncio.wait_for(
                    connection.run(command, check=False),
                    timeout=self.settings.ssh_connect_timeout_seconds,
                )
            finally:
                connection.close()
                await connection.wait_closed()
        except (asyncssh.Error, OSError, TimeoutError) as exc:
            raise AppError(
                503,
                "student_ssh_unavailable",
                "SSH-аутентификация student не прошла.",
                {"error": type(exc).__name__},
            ) from exc
        try:
            payload = json.loads(result.stdout or "")
        except json.JSONDecodeError as exc:
            raise AppError(
                409,
                "student_boundary_invalid",
                "Проверка границ student вернула некорректный JSON.",
            ) from exc
        safe = bool(
            result.exit_status == 0
            and payload.get("ssh_authenticated") is True
            and payload.get("sudo_access") is False
            and payload.get("docker_socket_access") is False
        )
        return {**payload, "safe": safe}

    async def get_or_start(self, run_id: int) -> TerminalSession:
        async with self._lock:
            existing = self.sessions.get(run_id)
            if existing and not existing.closed:
                return existing
            if self.protector is None:
                raise AppError(
                    503, "secret_storage_unavailable", "SSH secrets недоступны на этом host."
                )
            with self.database.session_factory() as session:
                run = session.get(LabRun, run_id)
                host = session.query(LinuxHost).order_by(LinuxHost.id).first()
                if run is None or run.status != "active":
                    raise AppError(404, "active_run_not_found", "Активный lab run не найден.")
                if host is None:
                    raise AppError(409, "linux_host_missing", "Linux VM ещё не настроена.")
                initial_transcript = run.transcript
                initial_commands = list(run.terminal_inputs or [])
                initial_command_offsets = list(run.terminal_input_offsets or [])
                initial_input_kinds = list(run.terminal_input_kinds or [])
                session.expunge(host)
            await self.wake(host)
            known_hosts = write_known_hosts(self.settings, host)
            key = import_private_key(host, self.protector)
            try:
                connection = await asyncio.wait_for(
                    asyncssh.connect(
                        host.host,
                        port=host.port,
                        username=host.username,
                        client_keys=[key],
                        known_hosts=str(known_hosts),
                        agent_path=None,
                    ),
                    timeout=self.settings.ssh_connect_timeout_seconds,
                )
                process = await connection.create_process(
                    command="env INPUTRC=/dev/null /bin/bash --noprofile --norc -i",
                    term_type="xterm-256color",
                    term_size=(120, 32),
                    stderr=asyncssh.STDOUT,
                )
            except (asyncssh.Error, OSError, TimeoutError) as exc:
                raise AppError(
                    503,
                    "ssh_terminal_failed",
                    "Не удалось открыть terminal в подтверждённой Linux VM.",
                    {"error": type(exc).__name__},
                ) from exc
            session_id = uuid.uuid4().hex
            marker = f"__CRC_INPUT_READY_{session_id}__"
            failure_marker = f"__CRC_INPUT_FAILED_{session_id}__"
            initialization = (
                "stty -echo\n"
                "bind 'set editing-mode emacs'\n"
                "bind 'set enable-bracketed-paste off'\n"
                "bind '\"\\C-a\": beginning-of-line'\n"
                "bind '\"\\C-e\": end-of-line'\n"
                "bind '\"\\C-u\": unix-line-discard'\n"
                "bind '\"\\C-k\": kill-line'\n"
                "bind '\"\\e[D\": backward-char'\n"
                "bind '\"\\e[C\": forward-char'\n"
                "bind '\"\\e[H\": beginning-of-line'\n"
                "bind '\"\\e[F\": end-of-line'\n"
                "bind '\"\\e[3~\": delete-char'\n"
                "if bind -v | grep -q '^set editing-mode emacs$' "
                "&& bind -q beginning-of-line | grep -Fq '\\C-a' "
                "&& bind -q end-of-line | grep -Fq '\\C-e' "
                "&& bind -q unix-line-discard | grep -Fq '\\C-u' "
                "&& bind -q kill-line | grep -Fq '\\C-k'; then\n"
                f"  printf '\\n{marker}\\n'\n"
                "else\n"
                f"  printf '\\n{failure_marker}\\n'\n"
                "fi\n"
                "stty echo\n"
            )
            process.stdin.write(initialization)
            await process.stdin.drain()
            with self.database.session_factory() as session:
                stored = session.get(LabRun, run_id)
                if stored is not None:
                    stored.input_integrity = "initializing"
                    stored.input_integrity_reason = None
                    stored.terminal_session_id = session_id
                    session.commit()
            terminal = TerminalSession(
                run_id,
                connection,
                process,
                self.database,
                self.settings.max_transcript_bytes,
                self._finished,
                initial_transcript=initial_transcript,
                initial_commands=initial_commands,
                initial_command_offsets=initial_command_offsets,
                initial_input_kinds=initial_input_kinds,
                initialization_marker=marker,
                initialization_failure_marker=failure_marker,
            )
            self.sessions[run_id] = terminal
            return terminal

    def _finished(self, run_id: int) -> None:
        self.sessions.pop(run_id, None)

    async def stop(self, run_id: int) -> None:
        terminal = self.sessions.pop(run_id, None)
        if terminal:
            await terminal.close()

    async def flush(self, run_id: int) -> None:
        terminal = self.sessions.get(run_id)
        if terminal and not terminal.closed:
            await terminal.flush()

    async def stop_all(self) -> None:
        for run_id in tuple(self.sessions):
            await self.stop(run_id)


MISSION_DIRECTORY = re.compile(r"^[a-z0-9][a-z0-9-]+$")


async def seed_student_missions(runner: RangeRunner, variant_id: str, archive: bytes) -> None:
    """Unpack mission files into ~/missions/<variant> as the learner, nowhere else."""
    if not MISSION_DIRECTORY.fullmatch(variant_id):
        raise AppError(400, "mission_variant_invalid", "Недопустимое имя варианта миссии.")
    if runner.protector is None:
        raise AppError(503, "secret_storage_unavailable", "SSH secret storage недоступно.")
    host = runner._host()
    await runner.wake(host)
    known_hosts = write_known_hosts(runner.settings, host)
    key = import_private_key(host, runner.protector)
    command = (
        "set -eu; "
        f'd="$HOME/missions/{variant_id}"; '
        'rm -rf -- "$d"; mkdir -p -- "$d"; '
        'tar -xzf - -C "$d" --no-same-owner --no-overwrite-dir'
    )
    try:
        connection = await asyncio.wait_for(
            asyncssh.connect(
                host.host,
                port=host.port,
                username=host.username,
                client_keys=[key],
                known_hosts=str(known_hosts),
                agent_path=None,
            ),
            timeout=runner.settings.ssh_connect_timeout_seconds,
        )
        try:
            result = await asyncio.wait_for(
                connection.run(command, input=archive, encoding=None, check=False),
                timeout=runner.settings.ssh_connect_timeout_seconds,
            )
        finally:
            connection.close()
            await connection.wait_closed()
    except (asyncssh.Error, OSError, TimeoutError) as exc:
        raise AppError(
            503,
            "mission_seed_failed",
            "Не удалось разложить файлы миссии в Linux VM.",
            {"error": type(exc).__name__},
        ) from exc
    if result.exit_status != 0:
        raise AppError(
            409,
            "mission_seed_failed",
            "Linux VM отклонила раскладку файлов миссии.",
            {"exit_status": result.exit_status},
        )
