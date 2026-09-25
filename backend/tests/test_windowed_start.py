from __future__ import annotations

import logging
import sys

import pytest
import uvicorn

from cyber_range_coach import cli


@pytest.fixture
def windowed(monkeypatch, tmp_path):
    """PyInstaller console=False: the process has no stdout and no stderr."""
    monkeypatch.setenv("CRC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CRC_ALLOW_INSECURE_DEV_SECRETS", "true")
    root = logging.getLogger()
    saved = list(root.handlers)
    yield tmp_path
    for handler in list(root.handlers):
        if handler not in saved:
            root.removeHandler(handler)
            handler.close()


def test_academy_starts_without_console_and_logs_to_file(windowed, monkeypatch) -> None:
    started: dict[str, object] = {}

    def fake_run(app, **kwargs):
        # uvicorn.run builds Config first; that is where the windowed exe crashed
        # with "Unable to configure formatter 'default'".
        uvicorn.Config(app, **kwargs)
        started["ok"] = True

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    # Set inside the test body: pytest re-installs its own capture streams
    # between fixture setup and the call phase.
    saved_streams = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = None, None
    try:
        cli.configure_console_encoding()
        code = cli.serve(lan=False, no_browser=True)
        stream_handlers = [
            handler
            for handler in logging.getLogger().handlers
            if type(handler) is logging.StreamHandler
        ]
    finally:
        sys.stdout, sys.stderr = saved_streams
    assert code == 0
    assert stream_handlers == [], "no console: a StreamHandler would write to None"
    assert started["ok"] is True
    logging.getLogger("cyber_range_coach").warning("windowed start check")
    for handler in logging.getLogger().handlers:
        handler.flush()
    log_files = list(windowed.rglob("academy.log"))
    assert log_files and "windowed start check" in log_files[0].read_text(encoding="utf-8")
