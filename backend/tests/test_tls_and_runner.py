from __future__ import annotations

from pathlib import Path

import pytest

from cyber_range_coach.errors import AppError
from cyber_range_coach.services.preflight import (
    has_active_private_profile,
    missing_learning_tools,
)
from cyber_range_coach.services.tls import certificate_ip_addresses, generate_certificates

ROOT = Path(__file__).resolve().parents[2]
WINDOWS_POWERSHELL_SCRIPTS = (
    ROOT / "scripts" / "package-windows.ps1",
    ROOT / "scripts" / "prepare-ocr.ps1",
    ROOT / "installer" / "windows" / "configure-firewall.ps1",
    ROOT / "installer" / "windows" / "remove-firewall.ps1",
)


def test_certificate_generation_is_idempotent(client) -> None:
    first = generate_certificates(client.app.state.settings, client.app.state.protector)
    second = generate_certificates(client.app.state.settings, client.app.state.protector)
    assert first["changed"] == "true"
    assert second["changed"] == "false"
    assert second["fingerprint"] == first["fingerprint"]
    assert "127.0.0.1" in certificate_ip_addresses(client.app.state.settings)


@pytest.mark.asyncio
async def test_range_runner_rejects_port_outside_relay_range(client) -> None:
    with pytest.raises(AppError) as error:
        await client.app.state.range_runner.run("relay 1")
    assert error.value.code == "runner_command_denied"


def test_installer_trusts_ca_via_original_user_application_context() -> None:
    source = (ROOT / "installer" / "windows" / "CyberRangeCoach.iss").read_text(encoding="utf-8")
    assert 'Parameters: "setup --trust-certificate"' in source
    assert 'Filename: "certutil.exe"' not in source
    assert "{localappdata}\\CyberRangeCoach\\certificates" not in source


def test_packaging_builds_a_real_console_doctor_executable() -> None:
    pyinstaller = (ROOT / "installer" / "windows" / "CyberRangeCoach.spec").read_text(
        encoding="utf-8"
    )
    inno = (ROOT / "installer" / "windows" / "CyberRangeCoach.iss").read_text(
        encoding="utf-8"
    )
    assert 'name="CyberRangeCoachDoctor"' in pyinstaller
    assert "doctor_exe = EXE(" in pyinstaller
    assert "console=True" in pyinstaller
    assert 'DestName: "CyberRangeCoachDoctor.exe"' not in inno


def test_windows_powershell_scripts_with_russian_text_have_utf8_bom() -> None:
    for script in WINDOWS_POWERSHELL_SCRIPTS:
        source = script.read_bytes()
        assert any(byte > 0x7F for byte in source)
        assert source.startswith(b"\xef\xbb\xbf"), script


def test_firewall_script_requires_an_active_private_ipv4_profile() -> None:
    source = (ROOT / "installer" / "windows" / "configure-firewall.ps1").read_text(
        encoding="utf-8"
    )
    assert '@("Subnet", "LocalNetwork", "Internet")' in source
    assert '$_.NetworkCategory -eq "Private"' in source
    assert "-Profile Private" in source


def test_runner_tools_fail_closed_when_one_course_tool_is_missing() -> None:
    evidence: dict[str, object] = {
        "protocol": "crc-range-check/v1",
        "check": "tools",
        "tools": {"curl": True},
    }
    missing = missing_learning_tools(evidence, "crc-range-check/v1")
    assert "nmap" in missing
    assert "less" in missing
    assert "install" in missing


def test_ocr_language_hashes_are_identical_in_script_and_manifest() -> None:
    script = (ROOT / "scripts" / "prepare-ocr.ps1").read_text(encoding="utf-8")
    manifest = (ROOT / "vendor" / "tesseract" / "README.md").read_text(encoding="utf-8")
    for digest in (
        "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
        "e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225",
    ):
        assert digest in script
        assert digest in manifest


def test_windows_private_profile_must_be_active_on_ipv4() -> None:
    disconnected = [{"NetworkCategory": "Private", "IPv4Connectivity": "Disconnected"}]
    active = [{"NetworkCategory": "Private", "IPv4Connectivity": "Internet"}]
    assert has_active_private_profile(disconnected) is False
    assert has_active_private_profile(active) is True
