"""Owner's laptop 25.09.2026: WSL Ubuntu stops seconds after the last wsl.exe
process, SSH to 127.0.0.1:22 is refused; the probe showed the RSA fingerprint
while the page asked to compare the ed25519 one."""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path

import asyncssh
import pytest

from cyber_range_coach.models import LinuxHost
from cyber_range_coach.services import ssh as ssh_service
from cyber_range_coach.services import wsl as wsl_service
from cyber_range_coach.services.commands import CommandResult
from cyber_range_coach.services.ssh import host_key_check_command, probe_linux_host


class _Protector:
    def protect(self, value: bytes) -> str:
        return value.decode("utf-8")

    def unprotect(self, value: str) -> bytes:
        return value.encode("utf-8")


def _host(port: int, private_key: str = "unused", public_key: str = "unused") -> LinuxHost:
    return LinuxHost(
        id=1,
        name="WSL Ubuntu",
        host="127.0.0.1",
        port=port,
        username="student",
        runner_username="range-runner",
        encrypted_private_key=private_key,
        public_key=public_key,
        encrypted_runner_private_key="unused",
        runner_public_key="unused",
    )


class _ListRunner:
    async def run(self, *_argv: str, **_kwargs: object) -> CommandResult:
        return CommandResult(("wsl.exe",), 0, "Ubuntu\n", "")


def _fake_wsl(tmp_path: Path) -> Path:
    script = tmp_path / "wsl.exe"
    script.write_text("#!/bin/sh\nexec sleep 1000\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


async def test_keepalive_starts_one_process_and_waits_for_sshd(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wsl_service, "follows_wsl_address", lambda _host: True)
    monkeypatch.setattr(wsl_service.shutil, "which", lambda _name: str(_fake_wsl(tmp_path)))
    keepalive = wsl_service.WslKeepAlive(_ListRunner(), 5.0, ssh_wait_seconds=10.0)  # type: ignore[arg-type]

    async def accept(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    probe = await asyncio.start_server(accept, "127.0.0.1", 0)
    port = probe.sockets[0].getsockname()[1]
    probe.close()
    await probe.wait_closed()

    async def sshd_comes_up_late() -> asyncio.Server:
        await asyncio.sleep(1.5)
        return await asyncio.start_server(accept, "127.0.0.1", port)

    late = asyncio.create_task(sshd_comes_up_late())
    try:
        started = asyncio.get_running_loop().time()
        await keepalive.ensure(_host(port))
        assert asyncio.get_running_loop().time() - started >= 1.0, "must wait for sshd"
        first = keepalive._process
        assert first is not None and first.returncode is None
        await keepalive.ensure(_host(port))
        assert keepalive._process is first, "one keep-alive process, not one per call"
    finally:
        await keepalive.close()
        server = await late
        server.close()
        await server.wait_closed()
    assert first.returncode is not None, "academy exit stops the keep-alive"


async def test_keepalive_restarts_after_wsl_process_dies(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wsl_service, "follows_wsl_address", lambda _host: True)
    monkeypatch.setattr(wsl_service.shutil, "which", lambda _name: str(_fake_wsl(tmp_path)))
    keepalive = wsl_service.WslKeepAlive(_ListRunner(), 5.0, ssh_wait_seconds=0.0)  # type: ignore[arg-type]
    try:
        await keepalive.ensure(_host(1))
        first = keepalive._process
        assert first is not None
        first.kill()
        await first.wait()
        await keepalive.ensure(_host(1))
        assert keepalive._process is not first and keepalive._process is not None
    finally:
        await keepalive.close()


async def test_keepalive_ignores_non_wsl_hosts(monkeypatch) -> None:
    monkeypatch.setattr(wsl_service, "follows_wsl_address", lambda _host: False)
    keepalive = wsl_service.WslKeepAlive(_ListRunner(), 5.0)  # type: ignore[arg-type]
    await keepalive.ensure(_host(22))
    assert keepalive._process is None


async def test_probe_wakes_linux_before_connecting(monkeypatch) -> None:
    woken: list[str] = []

    async def waker(host: LinuxHost) -> None:
        woken.append(host.host)

    async def refused(*_args: object) -> tuple[bool, str]:
        assert woken, "wake must happen before the TCP check"
        return False, "refused"

    monkeypatch.setattr(ssh_service, "tcp_connect", refused)
    await probe_linux_host(_host(22), _Protector(), 1.0, waker)  # type: ignore[arg-type]
    assert woken == ["127.0.0.1"]


class _AcceptKey(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def public_key_auth_supported(self) -> bool:
        return True

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        return True


async def test_probe_reports_ed25519_and_the_matching_check_command() -> None:
    rsa = asyncssh.generate_private_key("ssh-rsa")
    ed25519 = asyncssh.generate_private_key("ssh-ed25519")
    server = await asyncssh.create_server(
        _AcceptKey, "127.0.0.1", 0, server_host_keys=[rsa, ed25519]
    )
    port = server.sockets[0].getsockname()[1]
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    private = client_key.export_private_key(format_name="openssh").decode("utf-8")
    try:
        result = await probe_linux_host(
            _host(port, private_key=private), _Protector(), 5.0  # type: ignore[arg-type]
        )
    finally:
        server.close()
        await server.wait_closed()
    assert result.ssh_authenticated, result.detail
    assert result.fingerprint == ed25519.get_fingerprint()
    assert result.host_key is not None and result.host_key.startswith("ssh-ed25519 ")
    assert "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub" in result.detail


@pytest.mark.parametrize(
    ("algorithm", "path"),
    [
        ("ssh-ed25519", "/etc/ssh/ssh_host_ed25519_key.pub"),
        ("rsa-sha2-512", "/etc/ssh/ssh_host_rsa_key.pub"),
        ("ssh-rsa", "/etc/ssh/ssh_host_rsa_key.pub"),
        ("ecdsa-sha2-nistp256", "/etc/ssh/ssh_host_ecdsa_key.pub"),
    ],
)
def test_check_command_follows_key_type(algorithm: str, path: str) -> None:
    assert host_key_check_command(algorithm) == f"ssh-keygen -lf {path}"


async def test_runner_check_wakes_linux_before_ssh(client, monkeypatch) -> None:
    from datetime import UTC, datetime

    from cyber_range_coach.services.ssh import RangeRunner

    events: list[str] = []

    async def waker(_host: LinuxHost) -> None:
        events.append("wake")

    async def fake_connect(*_args: object, **_kwargs: object) -> object:
        events.append("connect")
        raise OSError("stop here")

    db = client.app.state.db
    with db.session_factory() as session:
        host = _host(22)
        host.id = None
        host.host_key = "ssh-ed25519 AAAA"
        host.host_key_fingerprint = "SHA256:test"
        host.confirmed_at = datetime.now(UTC)
        session.add(host)
        session.commit()
    monkeypatch.setattr(ssh_service.asyncssh, "connect", fake_connect)
    monkeypatch.setattr(ssh_service, "import_runner_private_key", lambda *_args: object())
    runner = RangeRunner(client.app.state.settings, db, _Protector(), waker)  # type: ignore[arg-type]
    with pytest.raises(Exception, match="недоступна"):
        await runner.tools()
    assert events == ["wake", "connect"]
