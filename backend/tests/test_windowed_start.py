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


def test_lan_start_reissues_certificate_after_address_change(windowed, monkeypatch) -> None:
    from cyber_range_coach.config import Settings
    from cyber_range_coach.schemas import NetworkInterface
    from cyber_range_coach.services import tls
    from cyber_range_coach.services.secrets import build_secret_protector

    def lan(address: str):
        return lambda: [NetworkInterface(address=address, private=True, loopback=False)]

    settings = Settings()
    settings.ensure_directories()
    protector = build_secret_protector(settings.data_dir, True)
    monkeypatch.setattr(tls, "local_interfaces", lan("192.168.10.10"))
    tls.generate_certificates(settings, protector)
    monkeypatch.setattr(tls, "local_interfaces", lan("192.168.10.11"))
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: None)
    assert cli.serve(lan=True, no_browser=True) == 0
    assert "192.168.10.11" in tls.certificate_ip_addresses(settings)


def test_failed_reissue_does_not_stop_the_academy(windowed, monkeypatch) -> None:
    from cyber_range_coach.config import Settings
    from cyber_range_coach.schemas import NetworkInterface
    from cyber_range_coach.services import tls
    from cyber_range_coach.services.secrets import build_secret_protector

    settings = Settings()
    settings.ensure_directories()
    monkeypatch.setattr(
        tls, "local_interfaces",
        lambda: [NetworkInterface(address="192.168.10.10", private=True, loopback=False)],
    )
    tls.generate_certificates(settings, build_secret_protector(settings.data_dir, True))

    def broken(*_args, **_kwargs):
        raise ValueError("unexpected CA key type")

    monkeypatch.setattr(cli, "ensure_certificate_covers_lan", broken)
    started: dict[str, object] = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: started.update(kwargs))
    assert cli.serve(lan=True, no_browser=True) == 0
    assert started["ssl_certfile"]
