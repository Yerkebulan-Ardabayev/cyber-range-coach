from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

from cyber_range_coach.instance import SingleInstanceLock


def test_windows_lock_uses_same_fixed_byte_for_lock_and_unlock(
    tmp_path: Path, monkeypatch
) -> None:
    lock = SingleInstanceLock(tmp_path / "academy.lock")
    fake_msvcrt = Mock()

    monkeypatch.setattr("cyber_range_coach.instance.os.name", "nt")
    monkeypatch.setattr(
        "cyber_range_coach.instance.import_module", lambda _name: fake_msvcrt
    )

    with lock:
        assert lock.handle is not None
        assert lock.handle.tell() == 0

    calls = fake_msvcrt.locking.call_args_list
    assert len(calls) == 2
    assert calls[0].args[2] == 1
    assert calls[1].args[2] == 1


def test_second_process_cannot_acquire_instance_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "process.lock"
    holder_code = """
import sys
from pathlib import Path
from cyber_range_coach.instance import SingleInstanceLock
with SingleInstanceLock(Path(sys.argv[1])):
    print("locked", flush=True)
    sys.stdin.readline()
"""
    contender_code = """
import sys
from pathlib import Path
from cyber_range_coach.instance import InstanceAlreadyRunning, SingleInstanceLock
try:
    with SingleInstanceLock(Path(sys.argv[1])):
        raise SystemExit(0)
except InstanceAlreadyRunning:
    raise SystemExit(17)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        contender = subprocess.run(
            [sys.executable, "-c", contender_code, str(lock_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert contender.returncode == 17, contender.stderr
    finally:
        if holder.stdin is not None:
            holder.stdin.write("release\n")
            holder.stdin.flush()
        holder.wait(timeout=10)
