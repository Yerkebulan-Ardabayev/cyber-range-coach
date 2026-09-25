from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from typing import BinaryIO


class InstanceAlreadyRunning(RuntimeError):
    pass


class SingleInstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle: BinaryIO | None = None

    def __enter__(self) -> SingleInstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                msvcrt = import_module("msvcrt")

                self.handle.seek(0, os.SEEK_END)
                if self.handle.tell() == 0:
                    self.handle.write(b"0")
                    self.handle.flush()
                # msvcrt.locking starts at the current file offset. Every
                # process must therefore lock the same fixed byte.
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise InstanceAlreadyRunning("Cyber Range Coach уже запущен") from exc
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                msvcrt = import_module("msvcrt")

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


STOP_REQUEST_NAME = "stop-request"


def request_stop(lock_path: Path, timeout_seconds: float = 20.0) -> bool:
    """Ask a running academy to exit and wait until its instance lock is free.

    The Windows installer runs this before replacing files: Restart Manager
    cannot close the windowed academy (owner's laptop, 25.09.2026), so the
    academy watches this file and shuts down on its own. True when no academy
    is running any more.
    """
    import time

    stop_file = lock_path.with_name(STOP_REQUEST_NAME)
    deadline = time.monotonic() + timeout_seconds
    requested = False
    try:
        while True:
            try:
                with SingleInstanceLock(lock_path):
                    return True
            except InstanceAlreadyRunning:
                pass
            if not requested:
                stop_file.parent.mkdir(parents=True, exist_ok=True)
                stop_file.write_text("stop\n", encoding="utf-8")
                requested = True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)
    finally:
        if requested:
            stop_file.unlink(missing_ok=True)
