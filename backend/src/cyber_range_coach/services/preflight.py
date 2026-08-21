from __future__ import annotations

import json
import platform
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from ..config import Settings
from ..database import Database
from ..errors import AppError
from ..models import LinuxHost
from ..schemas import CheckResult, NetworkResponse, PreflightResponse
from .commands import SafeCommandRunner
from .docker import DockerDiscovery
from .network import local_interfaces, tcp_connect
from .ssh import RangeRunner, TerminalManager
from .tls import (
    CA_CERT,
    CA_KEY,
    SERVER_CERT,
    SERVER_KEY,
    certificate_fingerprint,
    certificate_ip_addresses,
)

REQUIRED_LEARNING_TOOLS = frozenset(
    {
        "awk",
        "base64",
        "bash",
        "cat",
        "curl",
        "find",
        "getent",
        "grep",
        "id",
        "ip",
        "install",
        "less",
        "ls",
        "mktemp",
        "nc",
        "nmap",
        "pwd",
        "rm",
        "sort",
        "stat",
        "tail",
        "timeout",
        "touch",
        "tr",
    }
)
ACTIVE_IPV4_STATES = frozenset({"Subnet", "LocalNetwork", "Internet"})


def missing_learning_tools(evidence: dict[str, object], protocol: str) -> list[str]:
    if evidence.get("protocol") != protocol or evidence.get("check") != "tools":
        return sorted(REQUIRED_LEARNING_TOOLS)
    tools = evidence.get("tools")
    if not isinstance(tools, dict):
        return sorted(REQUIRED_LEARNING_TOOLS)
    return sorted(tool for tool in REQUIRED_LEARNING_TOOLS if tools.get(tool) is not True)


def has_active_private_profile(profiles: list[object]) -> bool:
    return any(
        isinstance(item, dict)
        and item.get("NetworkCategory") == "Private"
        and item.get("IPv4Connectivity") in ACTIVE_IPV4_STATES
        for item in profiles
    )


class PreflightService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        runner: SafeCommandRunner,
        docker: DockerDiscovery,
        range_runner: RangeRunner,
        terminals: TerminalManager,
    ) -> None:
        self.settings = settings
        self.database = database
        self.runner = runner
        self.docker = docker
        self.range_runner = range_runner
        self.terminals = terminals

    async def run(self) -> PreflightResponse:
        checks: list[CheckResult] = []
        is_windows = sys.platform == "win32"
        checks.append(
            CheckResult(
                id="platform",
                status="ok" if is_windows else "warning",
                title="Windows-хост",
                detail=(
                    f"Обнаружена Windows {platform.release()}."
                    if is_windows
                    else f"Хост разработки: {platform.system()} {platform.release()}."
                ),
                action=None if is_windows else "Production installer надо проверить на Windows.",
            )
        )
        integrity = self.database.integrity_check()
        checks.append(
            CheckResult(
                id="database",
                status="ok" if integrity == "ok" else "blocked",
                title="База академии",
                detail=f"Проверка целостности SQLite: {integrity}",
            )
        )
        docker_ok, docker_detail = await self.docker.available()
        context = await self.docker.context() if docker_ok else {"available": False}
        checks.append(
            CheckResult(
                id="docker",
                status="ok" if docker_ok else "blocked",
                title="Docker Desktop",
                detail=(
                    docker_detail
                    if docker_ok
                    else "Docker Engine не отвечает через локальный Docker CLI."
                ),
                action=None if docker_ok else "Запустите Docker Desktop и повторите preflight.",
                evidence=context,
            )
        )
        certificate_files = (CA_CERT, CA_KEY, SERVER_CERT, SERVER_KEY)
        tls_set_complete = all(
            (self.settings.certificates_dir / filename).exists() for filename in certificate_files
        )
        current_lan_addresses = {
            interface.address
            for interface in local_interfaces()
            if interface.private and not interface.loopback and ":" not in interface.address
        }
        missing_certificate_addresses = (
            current_lan_addresses - certificate_ip_addresses(self.settings)
            if tls_set_complete and self.settings.lan_mode
            else set()
        )
        tls_ready = (
            self.settings.tls_enabled and tls_set_complete and not missing_certificate_addresses
        )
        checks.append(
            CheckResult(
                id="tls",
                status="ok"
                if tls_ready
                else ("warning" if not self.settings.lan_mode else "blocked"),
                title="Локальный HTTPS",
                detail=(
                    "Сертификат надо пересоздать для текущих LAN-адресов: "
                    + ", ".join(sorted(missing_certificate_addresses))
                    if missing_certificate_addresses
                    else (
                        f"Отпечаток сертификата: {certificate_fingerprint(self.settings)}"
                        if tls_set_complete
                        else "Набор локальных сертификатов отсутствует или неполон."
                    )
                ),
                action=(
                    None
                    if tls_ready
                    else "Создайте локальный сертификат и явно добавьте доверие до включения LAN mode."
                ),
            )
        )
        codex = self.runner.available("codex")
        claude = self.runner.available("claude")
        checks.append(
            CheckResult(
                id="ai_cli",
                status="unavailable",
                title="Необязательные AI CLI",
                detail=(
                    f"Внешний AI отключён. Codex CLI: {'найден' if codex else 'не найден'}; "
                    f"Claude CLI: {'найден' if claude else 'не найден'}."
                ),
                action="Windows-релиз использует локальные методические подсказки и не отправляет данные лаборатории.",
            )
        )
        with self.database.session_factory() as session:
            linux_host = session.scalars(select(LinuxHost).order_by(LinuxHost.id)).first()
        if linux_host is None:
            checks.append(
                CheckResult(
                    id="linux_vm",
                    status="blocked",
                    title="Linux VM",
                    detail="Профиль Linux VM ещё не настроен.",
                    action="Создайте SSH-ключ student и настройте профиль Linux VM.",
                )
            )
        else:
            reachable, detail = await tcp_connect(
                linux_host.host, linux_host.port, self.settings.ssh_connect_timeout_seconds
            )
            confirmed = bool(linux_host.confirmed_at and linux_host.host_key)
            checks.append(
                CheckResult(
                    id="linux_vm",
                    status="ok" if reachable and confirmed else "blocked",
                    title="Linux VM",
                    detail=(
                        f"{detail}; ключ хоста "
                        + ("подтверждён." if confirmed else "не подтверждён.")
                    ),
                    action=(
                        None
                        if reachable and confirmed
                        else "Запустите VM, добавьте созданный публичный ключ и подтвердите отпечаток хоста."
                    ),
                )
            )
            if reachable and confirmed:
                try:
                    student_evidence = await self.terminals.verify_student_boundary()
                    student_ok = student_evidence.get("safe") is True
                    checks.append(
                        CheckResult(
                            id="student_boundary",
                            status="ok" if student_ok else "blocked",
                            title="Граница прав Linux student",
                            detail=(
                                "Ключ student работает, non-interactive sudo и известные Docker sockets недоступны."
                                if student_ok
                                else "У student есть non-interactive sudo или доступ к известному Docker socket."
                            ),
                            action=None if student_ok else "Уберите лишние права student до запуска лабораторий.",
                            evidence=student_evidence,
                        )
                    )
                except AppError as exc:
                    checks.append(
                        CheckResult(
                            id="student_boundary",
                            status="blocked",
                            title="Граница прав Linux student",
                            detail=exc.message,
                            action="Проверьте ключ student и ограничения учётной записи.",
                            evidence={"code": exc.code},
                        )
                    )
                try:
                    runner_evidence = await self.range_runner.tools()
                    missing_tools = missing_learning_tools(
                        runner_evidence, self.range_runner.protocol
                    )
                    runner_ok = not missing_tools
                    checks.append(
                        CheckResult(
                            id="linux_tools",
                            status="ok" if runner_ok else "blocked",
                            title="Linux range-runner",
                            detail=(
                                "Ограниченный протокол runner и зафиксированные зависимости курса проверены."
                                if runner_ok
                                else "Отсутствующие или непроверенные инструменты: "
                                + ", ".join(missing_tools)
                            ),
                            action=None if runner_ok else "Повторно запустите проверенный Linux bootstrap.",
                            evidence=runner_evidence,
                        )
                    )
                except AppError as exc:
                    checks.append(
                        CheckResult(
                            id="linux_tools",
                            status="blocked",
                            title="Linux range-runner",
                            detail=exc.message,
                            action="Проверьте ключ range-runner и конфигурацию forced command.",
                            evidence={"code": exc.code},
                        )
                    )
        if is_windows:
            profile = await self._windows_network_profile()
            status = "ok" if profile.get("private") else "blocked"
            checks.append(
                CheckResult(
                    id="windows_network_profile",
                    status=status,
                    title="Сетевой профиль Windows",
                    detail=str(profile.get("detail")),
                    action=(
                        None
                        if status == "ok"
                        else "LAN mode остаётся выключенным, пока активная сеть не имеет профиль Private."
                    ),
                    evidence=profile,
                )
            )
        required_ids = {"database", "docker", "linux_vm"}
        if linux_host is not None:
            required_ids.update({"linux_tools", "student_boundary"})
        if self.settings.lan_mode:
            required_ids.add("tls")
            if is_windows:
                required_ids.add("windows_network_profile")
        ready = all(check.status == "ok" for check in checks if check.id in required_ids)
        if self.settings.environment == "production":
            ready = ready and is_windows
        return PreflightResponse(
            ready=ready,
            platform=platform.platform(),
            windows_supported=is_windows,
            checks=checks,
            generated_at=datetime.now(UTC),
        )

    async def _windows_network_profile(self) -> dict[str, object]:
        script = (
            "Get-NetConnectionProfile | "
            "Select-Object Name,InterfaceAlias,NetworkCategory,IPv4Connectivity | "
            "ConvertTo-Json -Compress"
        )
        result = await self.runner.run(
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script
        )
        if result.returncode != 0:
            return {"private": False, "detail": "Не удалось прочитать сетевой профиль Windows."}
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"private": False, "detail": "Windows вернула некорректные данные профиля."}
        profiles: list[object] = payload if isinstance(payload, list) else [payload]
        private = has_active_private_profile(profiles)
        return {
            "private": private,
            "detail": "Обнаружен активный IPv4-профиль Private."
            if private
            else "Активный профиль Private не обнаружен.",
            "profiles": profiles,
        }


def network_response(settings: Settings) -> NetworkResponse:
    interfaces = local_interfaces()
    scheme = "https" if settings.tls_enabled else "http"
    addresses = ["127.0.0.1"]
    if settings.lan_mode:
        addresses.extend(
            interface.address
            for interface in interfaces
            if interface.private and not interface.loopback and ":" not in interface.address
        )
    urls = [f"{scheme}://{address}:{settings.port}" for address in dict.fromkeys(addresses)]
    return NetworkResponse(
        bind_host=settings.bind_host,
        port=settings.port,
        lan_mode=settings.lan_mode,
        tls_enabled=settings.tls_enabled,
        interfaces=interfaces,
        academy_urls=urls,
    )
