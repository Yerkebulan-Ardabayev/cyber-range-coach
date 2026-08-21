from __future__ import annotations

import io
import sys

import pytest

from cyber_range_coach.cli import main


def test_help_reconfigures_legacy_console_before_printing_cyrillic(monkeypatch) -> None:
    output = io.BytesIO()
    legacy_stdout = io.TextIOWrapper(output, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", legacy_stdout)
    monkeypatch.setattr(sys, "argv", ["cyber-range-coach", "--help"])

    with pytest.raises(SystemExit) as exit_info:
        main()

    legacy_stdout.flush()
    assert exit_info.value.code == 0
    assert legacy_stdout.encoding.lower() == "utf-8"
    assert "Запустить локальную академию" in output.getvalue().decode("utf-8")
