from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cyber_range_coach.models import LinuxHost
from cyber_range_coach.services.commands import CommandResult
from cyber_range_coach.services.wsl import (
    current_wsl_source_ip,
    prepare_wsl_ubuntu,
    select_ubuntu_distribution,
    select_wsl_source_ip,
)


def command_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(("wsl.exe",), returncode, stdout, stderr)


def wsl_host() -> LinuxHost:
    return LinuxHost(
        id=1,
        name="WSL Ubuntu",
        host="127.0.0.1",
        port=22,
        username="student",
        runner_username="range-runner",
        encrypted_private_key="encrypted",
        public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestStudent",
        encrypted_runner_private_key="encrypted",
        runner_public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestRunner",
    )


def test_selects_exact_or_versioned_ubuntu_from_wsl_output() -> None:
    assert select_ubuntu_distribution("Debian\nUbuntu\nUbuntu-24.04\n") == "Ubuntu"
    assert select_ubuntu_distribution("U\x00b\x00u\x00n\x00t\x00u\x00-\x002\x004\x00.\x000\x004\x00") == "Ubuntu-24.04"
    assert select_ubuntu_distribution("Debian") is None
    assert select_wsl_source_ip("172.24.64.22 127.0.0.1") == "172.24.64.22"


@pytest.mark.asyncio
async def test_read_only_wsl_probe_does_not_start_stopped_distribution() -> None:
    runner = AsyncMock()
    runner.run = AsyncMock(
        side_effect=[command_result(stdout="Ubuntu\n"), command_result(stdout="")]
    )

    distribution, source_ip = await current_wsl_source_ip(runner, 8)

    assert distribution == "Ubuntu"
    assert source_ip is None
    assert runner.run.await_count == 2
    assert all("--exec" not in call.args for call in runner.run.await_args_list)


@pytest.mark.asyncio
async def test_wsl_wizard_stages_keys_and_explains_required_sudo_password(
    settings, monkeypatch
) -> None:
    monkeypatch.setattr(
        "cyber_range_coach.services.wsl.sys", SimpleNamespace(platform="win32")
    )
    responses = [
        command_result(stdout="Ubuntu\n"),
        command_result(stdout="172.24.64.22\n"),
        command_result(),
        command_result(),
        command_result(),
        command_result(stdout="/home/owner"),
        command_result(stdout="172.24.64.1\n"),
        command_result(returncode=1, stderr="sudo: a password is required"),
    ]
    runner = AsyncMock()
    runner.run = AsyncMock(side_effect=responses)

    result = await prepare_wsl_ubuntu(settings, runner, wsl_host())

    assert result.status == "sudo_password_required"
    assert result.distribution == "Ubuntu"
    assert result.relay_source_ip == "172.24.64.22"
    assert result.sudo_command is not None
    assert "sudo bash" in result.sudo_command
    assert "--student-user student" in result.sudo_command
    assert "--runner-user range-runner" in result.sudo_command
    assert "пароль" in result.detail
    staged_calls = runner.run.await_args_list[2:5]
    assert all(call.kwargs.get("stdin") for call in staged_calls)
