"""bootstrap-linux.sh on a real Ubuntu 24.04 sudo (1.9.15p5).

`sudo -l -U user` exits 0 there even for a user without any sudo rights, so the
check must read the output. Found on the owner's laptop 25.09.2026 (exit 78 on a
clean student)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

IMAGE = "cyber-range-coach-reference:24.04"
LINUX_DIR = Path(__file__).resolve().parents[2] / "installer" / "linux"
DOCKER = shutil.which("docker")
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBootstrapSudoTestKeyOnly0000000000000000"


def _image_available() -> bool:
    if DOCKER is None:
        return False
    probe = subprocess.run(
        [DOCKER, "image", "inspect", IMAGE], capture_output=True, check=False
    )
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not _image_available(), reason=f"нужен Docker и образ {IMAGE}"
)


def _bootstrap(prepare: str) -> subprocess.CompletedProcess[str]:
    assert DOCKER is not None
    script = f"""
set -e
{prepare}
cd /crc
bash bootstrap-linux.sh --student-key '{KEY}' --runner-key '{KEY}' --relay-host 172.30.160.1
"""
    return subprocess.run(
        [
            DOCKER, "run", "--rm", "-v", f"{LINUX_DIR}:/crc:ro", IMAGE,
            "bash", "-c", script,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_clean_student_passes_although_sudo_list_exits_zero() -> None:
    result = _bootstrap("true")
    assert result.returncode == 0, result.stderr
    assert "Роли Cyber Range Coach в Linux настроены." in result.stdout


@pytest.mark.parametrize(
    "rule",
    ["student ALL=(ALL) NOPASSWD: ALL", "student ALL=(ALL) ALL"],
)
def test_student_with_sudo_rule_is_stopped(rule: str) -> None:
    prepare = (
        "useradd --create-home --comment 'Cyber Range Coach' --shell /bin/bash student\n"
        f"printf '%s\\n' '{rule}' > /etc/sudoers.d/student\n"
        "chmod 0440 /etc/sudoers.d/student"
    )
    result = _bootstrap(prepare)
    assert result.returncode == 78, (result.returncode, result.stderr)
    assert "sudo" in result.stderr


def test_foreign_student_gets_a_handover_hint_that_works() -> None:
    foreign = _bootstrap("useradd --create-home --shell /bin/bash student")
    assert foreign.returncode == 73
    assert "sudo usermod -c 'Cyber Range Coach' student" in foreign.stderr

    handed_over = _bootstrap(
        "useradd --create-home --shell /bin/bash student\n"
        "usermod -c 'Cyber Range Coach' student"
    )
    assert handed_over.returncode == 0, handed_over.stderr
