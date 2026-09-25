"""Installer upgrade on the owner's laptop 25.09.2026 rolled back: Restart
Manager could not close the running windowed academy. `CyberRangeCoach stop`
asks it to exit through a file the academy watches."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from cyber_range_coach.instance import SingleInstanceLock, request_stop


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _academy_env(data_dir: Path, port: int) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        CRC_DATA_DIR=str(data_dir),
        CRC_PORT=str(port),
        CRC_TLS_ENABLED="false",
        CRC_ALLOW_INSECURE_DEV_SECRETS="true",
    )
    return env


def test_stop_command_ends_a_running_academy(tmp_path: Path) -> None:
    port = _free_port()
    env = _academy_env(tmp_path, port)
    academy = subprocess.Popen(
        [sys.executable, "-m", "cyber_range_coach", "serve", "--no-browser"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            assert academy.poll() is None, "academy exited during start"
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v2/devices/me", timeout=2)
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                assert time.monotonic() < deadline, "academy did not answer"
                time.sleep(0.5)
        stopped = subprocess.run(
            [sys.executable, "-m", "cyber_range_coach", "stop"],
            env=env,
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert stopped.returncode == 0, stopped.stderr
        assert academy.wait(timeout=15) == 0
    finally:
        if academy.poll() is None:
            academy.kill()
            academy.wait()


def test_stop_when_nothing_runs_succeeds_at_once(tmp_path: Path) -> None:
    started = time.monotonic()
    assert request_stop(tmp_path / "academy.lock", timeout_seconds=5) is True
    assert time.monotonic() - started < 2
    assert not (tmp_path / "stop-request").exists()


def test_stop_reports_failure_when_academy_ignores_it(tmp_path: Path) -> None:
    lock = tmp_path / "academy.lock"
    with SingleInstanceLock(lock):
        assert request_stop(lock, timeout_seconds=1) is False
    assert not (tmp_path / "stop-request").exists(), "no stale request for the next start"
