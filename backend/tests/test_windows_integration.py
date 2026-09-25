from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cyber_range_coach.models import LinuxHost
from cyber_range_coach.services.commands import CommandResult
from cyber_range_coach.services.preflight import REQUIRED_LEARNING_TOOLS
from cyber_range_coach.services.tls import generate_certificates


@pytest.mark.parametrize(
    ("current_wsl_source_ip", "expected_ready"),
    [("172.24.64.22", True), ("172.24.64.99", True), ("8.8.8.8", False)],
)
@pytest.mark.asyncio
async def test_private_wifi_ca_firewall_wsl_ssh_makes_doctor_ready(
    client, monkeypatch, current_wsl_source_ip: str, expected_ready: bool
) -> None:
    settings = client.app.state.settings
    settings.lan_mode = True
    settings.tls_enabled = True
    generate_certificates(settings, client.app.state.protector)
    with client.app.state.db.session_factory() as session:
        session.add(
            LinuxHost(
                name="WSL Ubuntu",
                host="127.0.0.1",
                port=22,
                relay_source_ip="172.24.64.22",
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

    # The keep-alive would start a real wsl.exe on the Windows runner; this
    # test covers preflight decisions, not waking WSL.
    monkeypatch.setattr(client.app.state.range_runner, "wake", AsyncMock())

    async def windows_command(_executable: str, *args: str, **_kwargs: object) -> CommandResult:
        if _executable == "wsl.exe":
            if "--exec" in args:
                return CommandResult(("wsl.exe",), 0, f"{current_wsl_source_ip}\n", "")
            return CommandResult(("wsl.exe",), 0, "Ubuntu\n", "")
        script = next((argument for argument in args if "ConvertTo-Json" in argument), "")
        if "CurrentUser\\Root" in script:
            assert str(args[-1]).endswith("cyber-range-coach-ca.crt")
            stdout = '{"Trusted":true,"Store":"CurrentUser\\\\Root"}'
        elif "Get-NetConnectionProfile" in script:
            stdout = (
                '[{"Name":"Private Wi-Fi","InterfaceAlias":"Wi-Fi",'
                '"NetworkCategoryValue":1,"NetworkCategoryName":"Private",'
                '"IPv4ConnectivityName":"Internet","IPv4Active":true}]'
            )
        elif "Get-NetFirewallRule" in script:
            stdout = (
                '{"Configured":true,"Exists":true,"ProfileValue":2,"Protocol":"TCP",'
                '"LocalPort":["8443"],"RemoteAddress":["LocalSubnet"]}'
            )
        else:
            raise AssertionError(f"Unexpected Windows command: {args!r}")
        return CommandResult(("powershell.exe",), 0, stdout, "")

    monkeypatch.setattr(
        "cyber_range_coach.services.preflight.sys", SimpleNamespace(platform="win32")
    )
    monkeypatch.setattr(
        "cyber_range_coach.services.preflight.local_interfaces", lambda: []
    )
    monkeypatch.setattr(
        "cyber_range_coach.services.preflight.tcp_connect",
        AsyncMock(return_value=(True, "TCP 127.0.0.1:22 доступен")),
    )
    client.app.state.preflight.runner.run = AsyncMock(side_effect=windows_command)
    client.app.state.preflight.docker.available = AsyncMock(
        return_value=(True, "Docker Engine отвечает")
    )
    client.app.state.preflight.docker.context = AsyncMock(
        return_value={"available": True, "name": "desktop-linux"}
    )
    client.app.state.preflight.terminals.verify_student_boundary = AsyncMock(
        return_value={"safe": True}
    )
    client.app.state.preflight.range_runner.tools = AsyncMock(
        return_value={
            "protocol": "crc-range-check/v1",
            "check": "tools",
            "tools": {tool: True for tool in REQUIRED_LEARNING_TOOLS},
        }
    )

    result = await client.app.state.preflight.run()

    checks = {check.id: check for check in result.checks}
    assert checks["windows_network_profile"].status == "ok"
    assert checks["tls"].status == "ok"
    assert checks["windows_firewall"].status == "ok"
    assert checks["linux_vm"].status == ("ok" if expected_ready else "blocked")
    assert checks["linux_vm"].evidence["stored_relay_source_ip"] == "172.24.64.22"
    assert checks["linux_vm"].evidence["relay_source_follows_wsl"] is True
    with client.app.state.db.session_factory() as session:
        stored = session.query(LinuxHost).one().relay_source_ip
    assert stored == "172.24.64.22", "preflight must stay read-only"
    assert checks["linux_vm"].evidence["current_wsl_source_ip"] == current_wsl_source_ip
    assert result.ready is expected_ready
