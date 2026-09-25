from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from cyber_range_coach.services import commands
from cyber_range_coach.services.commands import CREATE_NO_WINDOW, SafeCommandRunner


@pytest.mark.asyncio
async def test_windows_checks_start_console_tools_without_a_window(monkeypatch) -> None:
    """Opening «Полигон» flashed three PowerShell windows on the owner's laptop."""
    seen: dict[str, object] = {}

    class Done:
        returncode = 0

        async def communicate(self, _input=None):
            return b"ok", b""

    async def fake_exec(*argv, **kwargs):
        seen.update(kwargs)
        return Done()

    monkeypatch.setattr(commands, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(commands.shutil, "which", lambda name: f"C:/Windows/{name}")
    monkeypatch.setattr(commands.asyncio, "create_subprocess_exec", fake_exec)
    result = await SafeCommandRunner().run("powershell.exe", "-NoProfile", "-Command", "1")
    assert result.returncode == 0
    assert seen["creationflags"] == CREATE_NO_WINDOW


def test_no_window_flag_is_zero_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(commands, "sys", SimpleNamespace(platform=sys.platform if sys.platform != "win32" else "linux"))
    assert commands.hidden_window_flags() == 0


def test_every_process_launch_in_the_academy_hides_its_window() -> None:
    import ast
    from pathlib import Path

    source_root = Path(__file__).resolve().parents[1] / "src" / "cyber_range_coach"
    launches: list[str] = []
    missing: list[str] = []
    for path in source_root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if not isinstance(owner, ast.Name):
                continue
            launch = (owner.id == "subprocess" and node.func.attr in {"run", "Popen", "call", "check_output"}) or (
                owner.id == "asyncio" and node.func.attr in {"create_subprocess_exec", "create_subprocess_shell"}
            )
            if not launch:
                continue
            where = f"{path.name}:{node.lineno}"
            launches.append(where)
            if not any(keyword.arg == "creationflags" for keyword in node.keywords):
                missing.append(where)
    assert launches, "scan found no process launches"
    assert missing == []
