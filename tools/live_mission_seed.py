"""Live check of mission seeding over real SSH (AC-11-2).

Starts the reference Linux image with sshd, runs the application's own
``seed_student_missions`` against it and checks that files land only in
``/home/student/missions/<variant>``. Nothing runs on the host system.

    uv run python tools/live_mission_seed.py
"""

from __future__ import annotations

import asyncio
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import asyncssh

from cyber_range_coach.errors import AppError
from cyber_range_coach.services.command_practice import CommandCatalog
from cyber_range_coach.services.missions import MissionCatalog, mission_seed_archive
from cyber_range_coach.services.ssh import seed_student_missions

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "cyber-range-coach-reference:24.04"
CONTAINER = "crc-live-mission-seed"
MISSION = "magpie-missing-clue"
OUTSIDE = ("/home/student/evil-up.txt", "/home/evil-up.txt", "/srv/evil-abs.txt")
DOCKER = shutil.which("docker") or "/opt/homebrew/bin/docker"


def docker_sh(command: str) -> str:
    completed = subprocess.run(
        [DOCKER, "exec", CONTAINER, "bash", "-c", command],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout


def start_container(public_key: str) -> int:
    setup = f"""set -e
userdel -r ubuntu >/dev/null 2>&1 || true
useradd -m -u 1000 -s /bin/bash student
install -d -m 700 -o student -g student /home/student/.ssh
echo '{public_key}' > /home/student/.ssh/authorized_keys
chown student:student /home/student/.ssh/authorized_keys
chmod 600 /home/student/.ssh/authorized_keys
ssh-keygen -A >/dev/null
mkdir -p /run/sshd
exec /usr/sbin/sshd -D -e
"""
    subprocess.run([DOCKER, "rm", "-f", CONTAINER], capture_output=True, check=False)
    subprocess.run(
        [
            DOCKER,
            "run",
            "-d",
            "--name",
            CONTAINER,
            "-p",
            "127.0.0.1::22",
            "--entrypoint",
            "bash",
            IMAGE,
            "-c",
            setup,
        ],
        capture_output=True,
        check=True,
    )
    for _ in range(20):
        mapping = subprocess.run(
            [DOCKER, "port", CONTAINER, "22"], capture_output=True, text=True
        ).stdout
        if (
            mapping.strip()
            and docker_sh("test -S /run/sshd.pid -o -f /run/sshd.pid && echo up").strip() == "up"
        ):
            return int(mapping.strip().splitlines()[0].rsplit(":", 1)[1])
        time.sleep(0.5)
    raise RuntimeError("sshd did not start in the reference container")


def hostile_archive() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in ("../../evil-up.txt", "/srv/evil-abs.txt", "ok.txt"):
            data = b"x\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


async def run_checks(runner: SimpleNamespace) -> list[str]:
    errors: list[str] = []
    missions = MissionCatalog(
        ROOT / "curriculum" / "missions", CommandCatalog(ROOT / "curriculum" / "commands")
    )
    mission = missions.missions[MISSION]
    variant = mission.variants[0]
    archive = mission_seed_archive(mission, variant)
    await seed_student_missions(runner, variant.id, archive)
    await seed_student_missions(runner, variant.id, archive)
    expected = {entry.path for entry in variant.prepared_data if entry.kind != "directory"}
    listed = docker_sh(
        f"cd /home/student/missions/{variant.id} && find . -type f -printf '%P %u\\n'"
    )
    found = {line.split()[0]: line.split()[1] for line in listed.splitlines() if line.strip()}
    if set(found) != expected:
        errors.append(f"seeded files differ: {sorted(found)} != {sorted(expected)}")
    if any(owner != "student" for owner in found.values()):
        errors.append(f"seeded files not owned by student: {found}")
    try:
        await seed_student_missions(runner, "neg-test", hostile_archive())
    except AppError:
        pass
    for path in OUTSIDE:
        state = docker_sh(f"if test -e {path}; then echo present; else echo absent; fi").strip()
        if state != "absent":
            errors.append(f"cannot prove {path} is absent (got {state!r})")
    for bad in ("../x", "a/b", "X"):
        try:
            await seed_student_missions(runner, bad, archive)
            errors.append(f"invalid variant name accepted: {bad}")
        except AppError:
            pass
    return errors


def main() -> int:
    key = asyncssh.generate_private_key("ssh-ed25519")
    public_key = key.export_public_key().decode().strip()
    try:
        port = start_container(public_key)
        host_key = " ".join(docker_sh("cat /etc/ssh/ssh_host_ed25519_key.pub").split()[:2])
        host = SimpleNamespace(
            id=1,
            host="127.0.0.1",
            port=port,
            username="student",
            host_key=host_key,
            host_key_fingerprint="reference",
            confirmed_at=datetime.now(),
            encrypted_private_key=b"",
        )
        runner = SimpleNamespace(
            protector=SimpleNamespace(unprotect=lambda _blob: key.export_private_key()),
            settings=SimpleNamespace(
                runtime_dir=Path(tempfile.mkdtemp()), ssh_connect_timeout_seconds=10
            ),
            _host=lambda: host,
        )
        errors = asyncio.run(run_checks(runner))
    finally:
        subprocess.run([DOCKER, "rm", "-f", CONTAINER], capture_output=True, check=False)
    for message in errors:
        print(message)
    print("LIVE MISSION SEED " + ("FAILED" if errors else "PASSED"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
