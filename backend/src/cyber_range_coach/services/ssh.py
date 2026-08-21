from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any

import asyncssh
from fastapi import WebSocket

from ..config import Settings
from ..database import Database
from ..errors import AppError
from ..models import LabRun, LinuxHost
from ..schemas import LinuxProbeResponse
from .network import tcp_connect
from .secrets import SecretProtector


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
    host: LinuxHost, protector: SecretProtector, timeout: float
) -> LinuxProbeResponse:
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
            detail="SSH-аутентификация по ключу прошла. Сверьте показанный отпечаток хоста.",
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
    ) -> None:
        self.settings = settings
        self.database = database
        self.protector = protector

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
        self.reader_task = asyncio.create_task(self._read_output())
        self.close_task: asyncio.Task[None] | None = None
        self.closed = False

    async def _read_output(self) -> None:
        try:
            while True:
                chunk = await self.process.stdout.read(4096)
                if not chunk:
                    break
                self._append(str(chunk))
                await self._broadcast({"type": "output", "data": str(chunk)})
        except (asyncssh.Error, OSError):
            await self._broadcast(
                {"type": "error", "message": "Поток SSH-терминала прерван."}
            )
        finally:
            await self.flush()
            await self._broadcast(
                {"type": "exit", "exit_status": self.process.exit_status, "reconnectable": False}
            )
            self.closed = True
            self.connection.close()
            await self.connection.wait_closed()
            self.on_finished(self.run_id)

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
            self.pending_input = ""
            self.pending_input_start_offset = None
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
        await websocket.send_json({"type": "ready", "run_id": self.run_id})

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
        self._record_input(data)
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    def _record_input(self, data: str) -> None:
        for character in data:
            if character in {"\r", "\n"}:
                command = self.pending_input.strip()
                if command:
                    self.submitted_commands.append(command[:8000])
                    self.command_offsets.append(self.pending_input_start_offset or 0)
                    self.submitted_commands = self.submitted_commands[-100:]
                    self.command_offsets = self.command_offsets[-100:]
                self.pending_input = ""
                self.pending_input_start_offset = None
            elif character in {"\b", "\x7f"}:
                self.pending_input = self.pending_input[:-1]
            elif character >= " " and character != "\x7f":
                if not self.pending_input:
                    self.pending_input_start_offset = len(self.buffer)
                self.pending_input += character
                if len(self.pending_input) > 8000:
                    self.pending_input = self.pending_input[-8000:]

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


class TerminalManager:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        protector: SecretProtector | None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.protector = protector
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
                409, "student_boundary_invalid", "Проверка границ student вернула некорректный JSON."
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
                session.expunge(host)
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
