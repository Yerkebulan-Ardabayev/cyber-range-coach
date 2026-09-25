from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .app import create_app
from .config import Settings
from .doctor import collect
from .instance import InstanceAlreadyRunning, SingleInstanceLock
from .services.commands import hidden_window_flags
from .services.migration import write_v1_export
from .services.secrets import SecretProtectionError, build_secret_protector
from .services.tls import (
    CA_CERT,
    ensure_certificate_covers_lan,
    generate_certificates,
    materialize_server_key,
    remove_materialized_key,
)


def configure_console_encoding() -> None:
    """Keep Russian CLI output usable on legacy Windows console code pages."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="cyber-range-coach")
    subcommands = root.add_subparsers(dest="command")
    serve = subcommands.add_parser("serve", help="Запустить локальную академию")
    serve.add_argument("--lan", action="store_true", help="Слушать частную LAN после настройки")
    serve.add_argument("--no-browser", action="store_true")
    setup = subcommands.add_parser("setup", help="Подготовить локальные данные приложения")
    setup.add_argument("--generate-certificate", action="store_true")
    setup.add_argument("--force-certificate", action="store_true")
    setup.add_argument("--trust-certificate", action="store_true")
    subcommands.add_parser("doctor", help="Вывести read-only preflight в JSON")
    export = subcommands.add_parser("export-v1-notes", help="Экспортировать только полевые заметки из v1")
    export.add_argument("database", type=Path)
    export.add_argument("output", type=Path)
    return root


def has_console() -> bool:
    """False in the windowed Windows build (PyInstaller console=False): no std streams."""
    return sys.stdout is not None and sys.stderr is not None


def configure_logging(settings: Settings) -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(settings.logs_dir / "academy.log", encoding="utf-8")
    ]
    if has_console():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def serve(lan: bool, no_browser: bool) -> int:
    settings = Settings()
    if lan:
        settings.lan_mode = True
        settings.tls_enabled = True
        settings.bind_host = "0.0.0.0"
    settings.ensure_directories()
    configure_logging(settings)
    runtime_key: Path | None = None
    try:
        with SingleInstanceLock(settings.runtime_dir / "academy.lock"):
            ssl_certfile: str | None = None
            ssl_keyfile: str | None = None
            if settings.tls_enabled:
                protector = build_secret_protector(
                    settings.data_dir, settings.allow_insecure_dev_secrets
                )
                if ensure_certificate_covers_lan(settings, protector):
                    logging.getLogger(__name__).info(
                        "Сертификат сайта перевыпущен для текущих адресов (тот же локальный CA)."
                    )
                certificate, runtime_key = materialize_server_key(settings, protector)
                ssl_certfile = str(certificate)
                ssl_keyfile = str(runtime_key)
            app = create_app(settings)
            scheme = "https" if settings.tls_enabled else "http"
            local_url = f"{scheme}://127.0.0.1:{settings.port}"
            if not no_browser:
                threading.Timer(1.0, lambda: webbrowser.open(local_url)).start()
            uvicorn.run(
                app,
                host=settings.bind_host,
                port=settings.port,
                ssl_certfile=ssl_certfile,
                ssl_keyfile=ssl_keyfile,
                access_log=True,
                # Without a console uvicorn's own log config probes
                # sys.stdout.isatty() and the windowed exe dies at start;
                # None keeps uvicorn on the root logger set up above.
                log_config=None if not has_console() else uvicorn.config.LOGGING_CONFIG,
            )
    except InstanceAlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, SecretProtectionError) as exc:
        print(f"Требуется настройка TLS: {exc}", file=sys.stderr)
        return 3
    finally:
        remove_materialized_key(runtime_key)
    return 0


def main() -> None:
    configure_console_encoding()
    argv = sys.argv[1:]
    if not argv and Path(sys.argv[0]).stem.lower().endswith("doctor"):
        argv = ["doctor"]
    args = parser().parse_args(argv)
    command = args.command or "serve"
    if command == "serve":
        raise SystemExit(serve(getattr(args, "lan", False), getattr(args, "no_browser", False)))
    if command == "doctor":
        print(json.dumps(asyncio.run(collect()), ensure_ascii=False, indent=2))
        return
    if command == "setup":
        settings = Settings()
        settings.ensure_directories()
        if args.trust_certificate:
            if sys.platform != "win32":
                print("Добавление доверия сертификату поддерживается только на Windows.", file=sys.stderr)
                raise SystemExit(4)
            ca_certificate = settings.certificates_dir / CA_CERT
            if not ca_certificate.is_file():
                print("Сначала создайте локальный сертификат.", file=sys.stderr)
                raise SystemExit(4)
            windows_root = os.environ.get("SystemRoot")
            if not windows_root:
                print("Windows SystemRoot недоступен.", file=sys.stderr)
                raise SystemExit(4)
            certutil = Path(windows_root) / "System32" / "certutil.exe"
            if not certutil.is_file():
                print("Windows certutil.exe недоступен.", file=sys.stderr)
                raise SystemExit(4)
            completed = subprocess.run(
                [
                    str(certutil),
                    "-user",
                    "-addstore",
                    "Root",
                    str(ca_certificate),
                ],
                check=False,
                capture_output=True,
                text=True,
                creationflags=hidden_window_flags(),
            )
            if completed.returncode != 0:
                print("Windows отклонила добавление доверия локальному CA.", file=sys.stderr)
                raise SystemExit(4)
            print(json.dumps({"trusted": True, "ca_certificate": str(ca_certificate)}))
            return
        if not args.generate_certificate:
            print(json.dumps({"data_dir": str(settings.data_dir), "changed": False}))
            return
        protector = build_secret_protector(settings.data_dir, settings.allow_insecure_dev_secrets)
        result = generate_certificates(settings, protector, force=args.force_certificate)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if command == "export-v1-notes":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_v1_export(args.database.resolve(), args.output.resolve())
        print(json.dumps({"output": str(args.output.resolve()), "changed": True}))
        return
    raise SystemExit(2)


if __name__ == "__main__":
    main()
