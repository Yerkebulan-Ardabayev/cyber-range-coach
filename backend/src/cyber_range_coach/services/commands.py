from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass

# subprocess.CREATE_NO_WINDOW exists only on Windows; the value is fixed by Win32.
CREATE_NO_WINDOW = 0x08000000


def hidden_window_flags() -> int:
    """Windowed academy: console tools (powershell, wsl, docker) must not flash a window."""
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class SafeCommandRunner:
    """Run an explicit argv without a shell and with a bounded environment."""

    def __init__(self, timeout_seconds: float = 8.0):
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def available(executable: str) -> str | None:
        return shutil.which(executable)

    async def run(
        self,
        executable: str,
        *args: str,
        stdin: str | None = None,
        cwd: str | None = None,
        timeout_seconds: float | None = None,
        extra_env_keys: set[str] | None = None,
    ) -> CommandResult:
        resolved = shutil.which(executable)
        if resolved is None:
            return CommandResult((executable, *args), 127, "", f"{executable} is not installed")
        allowed_env = {
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "APPDATA",
            "USERPROFILE",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
        }
        allowed_env.update(extra_env_keys or set())
        safe_env = {key: value for key, value in os.environ.items() if key in allowed_env}
        process = await asyncio.create_subprocess_exec(
            resolved,
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=safe_env,
            creationflags=hidden_window_flags(),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(stdin.encode("utf-8") if stdin is not None else None),
                timeout=timeout_seconds or self.timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return CommandResult((resolved, *args), 124, "", "command timed out")
        return CommandResult(
            (resolved, *args),
            process.returncode or 0,
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
        )
