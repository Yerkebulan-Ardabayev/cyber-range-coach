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
from .relay import configured_relay_source_ip
from .ssh import RangeRunner, TerminalManager
from .tls import (
    CA_CERT,
    CA_KEY,
    SERVER_CERT,
    SERVER_KEY,
    certificate_fingerprint,
    certificate_ip_addresses,
)
from .wsl import acceptable_wsl_source_ip, current_wsl_source_ip

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
WINDOWS_PRIVATE_NETWORK_CATEGORY = 1
WINDOWS_FIREWALL_PRIVATE_PROFILE = 2
WINDOWS_ACADEMY_FIREWALL_RULE = "Cyber Range Coach UI 8443 Private LAN"


def missing_learning_tools(evidence: dict[str, object], protocol: str) -> list[str]:
    if evidence.get("protocol") != protocol or evidence.get("check") != "tools":
        return sorted(REQUIRED_LEARNING_TOOLS)
    tools = evidence.get("tools")
    if not isinstance(tools, dict):
        return sorted(REQUIRED_LEARNING_TOOLS)
    return sorted(tool for tool in REQUIRED_LEARNING_TOOLS if tools.get(tool) is not True)


def has_active_private_profile(profiles: list[object]) -> bool:
    for item in profiles:
        if not isinstance(item, dict):
            continue
        category = item.get("NetworkCategoryValue")
        if isinstance(category, bool):
            continue
        if isinstance(category, int):
            category_value = category
        elif isinstance(category, str) and category.isdecimal():
            category_value = int(category)
        else:
            continue
        if category_value == WINDOWS_PRIVATE_NETWORK_CATEGORY and item.get("IPv4Active") is True:
            return True
    return False


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
                detail=docker_detail,
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
        ca_trust: dict[str, object] = {
            "trusted": not is_windows,
            "store": "CurrentUser\\Root" if is_windows else None,
        }
        if is_windows and (self.settings.certificates_dir / CA_CERT).is_file():
            ca_trust = await self._windows_ca_trust()
        tls_ready = (
            self.settings.tls_enabled
            and tls_set_complete
            and not missing_certificate_addresses
            and ca_trust.get("trusted") is True
        )
        if missing_certificate_addresses:
            tls_detail = "Сертификат надо пересоздать для текущих LAN-адресов: " + ", ".join(
                sorted(missing_certificate_addresses)
            )
        elif tls_set_complete and is_windows and ca_trust.get("trusted") is not True:
            tls_detail = (
                "Локальный root CA не найден в Trusted Root Certification Authorities "
                "текущего пользователя (CurrentUser\\Root)."
            )
        elif tls_set_complete:
            tls_detail = (
                f"Root CA доверен; отпечаток серверного сертификата: "
                f"{certificate_fingerprint(self.settings)}"
                if is_windows
                else f"Отпечаток сертификата: {certificate_fingerprint(self.settings)}"
            )
        else:
            tls_detail = "Набор локальных сертификатов отсутствует или неполон."
        checks.append(
            CheckResult(
                id="tls",
                status="ok"
                if tls_ready
                else ("warning" if not self.settings.lan_mode else "blocked"),
                title="Локальный HTTPS",
                detail=tls_detail,
                action=(
                    None
                    if tls_ready
                    else "Перезапустите академию: сертификат сайта перевыпускается для нового адреса сам."
                    if missing_certificate_addresses
                    else "Создайте локальный сертификат и добавьте именно root CA в CurrentUser\\Root."
                ),
                evidence=ca_trust,
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
            # WSL stops without a wsl.exe process and a refused 127.0.0.1:22
            # would block the whole preflight (owner's laptop, 25.09.2026).
            await self.range_runner.wake(linux_host)
            reachable, detail = await tcp_connect(
                linux_host.host, linux_host.port, self.settings.ssh_connect_timeout_seconds
            )
            try:
                relay_source_ip = configured_relay_source_ip(linux_host)
            except AppError:
                relay_source_ip = None
            current_source_ip: str | None = None
            if is_windows and linux_host.host == "127.0.0.1":
                _, current_source_ip = await current_wsl_source_ip(
                    self.runner, self.settings.subprocess_timeout_seconds
                )
                if current_source_ip != relay_source_ip:
                    # WSL gets a new NAT address on every boot (spec 11.3 Zh).
                    # Preflight only reads: the relay start saves the live
                    # address itself, so a private WSL address is accepted here.
                    relay_source_ip = acceptable_wsl_source_ip(current_source_ip)
            confirmed = bool(
                linux_host.confirmed_at and linux_host.host_key and relay_source_ip
            )
            checks.append(
                CheckResult(
                    id="linux_vm",
                    status="ok" if reachable and confirmed else "blocked",
                    title="Linux VM",
                    detail=(
                        f"{detail}; ключ хоста "
                        + (
                            f"подтверждён; relay source {relay_source_ip}."
                            if confirmed
                            else "или отдельный relay source IP не подтверждён."
                        )
                    ),
                    action=(
                        None
                        if reachable and confirmed
                        else "Запустите VM, настройте relay source IP, добавьте ключ и подтвердите fingerprint."
                    ),
                    evidence={
                        "ssh_endpoint": f"{linux_host.host}:{linux_host.port}",
                        "stored_relay_source_ip": linux_host.relay_source_ip,
                        "current_wsl_source_ip": current_source_ip,
                        "relay_source_follows_wsl": bool(
                            is_windows and linux_host.host == "127.0.0.1"
                        ),
                    },
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
            firewall = await self._windows_firewall_status()
            firewall_status = (
                "ok"
                if firewall.get("configured") is True
                else ("blocked" if self.settings.lan_mode else "warning")
            )
            checks.append(
                CheckResult(
                    id="windows_firewall",
                    status=firewall_status,
                    title="Windows Firewall для академии",
                    detail=str(firewall.get("detail")),
                    action=(
                        None
                        if firewall_status == "ok"
                        else "Создайте правило TCP 8443 только для Private и LocalSubnet."
                    ),
                    evidence=firewall,
                )
            )
        required_ids = {"database", "docker", "linux_vm"}
        if linux_host is not None:
            required_ids.update({"linux_tools", "student_boundary"})
        if self.settings.lan_mode:
            required_ids.add("tls")
            if is_windows:
                required_ids.update({"windows_network_profile", "windows_firewall"})
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
            "$active = @('Subnet','LocalNetwork','Internet'); "
            "Get-NetConnectionProfile | ForEach-Object { "
            "[pscustomobject]@{Name=$_.Name;InterfaceAlias=$_.InterfaceAlias;"
            "NetworkCategoryValue=[int]$_.NetworkCategory;"
            "NetworkCategoryName=$_.NetworkCategory.ToString();"
            "IPv4ConnectivityName=$_.IPv4Connectivity.ToString();"
            "IPv4Active=($active -contains $_.IPv4Connectivity.ToString())} } | "
            "ConvertTo-Json -Compress"
        )
        result = await self.runner.run(
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
            timeout_seconds=self.settings.powershell_timeout_seconds,
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

    async def _windows_ca_trust(self) -> dict[str, object]:
        ca_path = self.settings.certificates_dir / CA_CERT
        if not ca_path.is_file():
            return {
                "trusted": False,
                "store": "CurrentUser\\Root",
                "detail": f"Файл {CA_CERT} отсутствует.",
            }
        script = (
            "$caPath=$args[0]; "
            "$ca=[System.Security.Cryptography.X509Certificates.X509Certificate2]::new($caPath); "
            "$thumbprint=$ca.Thumbprint; "
            "$path='Cert:\\CurrentUser\\Root\\' + $thumbprint; "
            "$trusted=$null -ne (Get-Item -LiteralPath $path -ErrorAction SilentlyContinue); "
            "[pscustomobject]@{Trusted=$trusted;Store='CurrentUser\\Root';"
            "CaThumbprint=$thumbprint} | ConvertTo-Json -Compress"
        )
        result = await self.runner.run(
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
            str(ca_path),
            timeout_seconds=self.settings.powershell_timeout_seconds,
        )
        if result.returncode != 0:
            return {
                "trusted": False,
                "store": "CurrentUser\\Root",
                "detail": "Не удалось проверить хранилище сертификатов текущего пользователя.",
            }
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "trusted": False,
                "store": "CurrentUser\\Root",
                "detail": "Windows вернула некорректный результат проверки root CA.",
            }
        trusted = isinstance(payload, dict) and payload.get("Trusted") is True
        return {
            "trusted": trusted,
            "store": "CurrentUser\\Root",
            "ca_thumbprint": payload.get("CaThumbprint") if isinstance(payload, dict) else None,
            "detail": (
                f"Файл {CA_CERT} найден в CurrentUser\\Root."
                if trusted
                else f"Файл {CA_CERT} не найден в CurrentUser\\Root."
            ),
        }

    async def _windows_firewall_status(self) -> dict[str, object]:
        script = (
            f"$rule=Get-NetFirewallRule -DisplayName '{WINDOWS_ACADEMY_FIREWALL_RULE}' "
            "-PolicyStore ActiveStore -ErrorAction SilentlyContinue | Select-Object -First 1; "
            "if ($null -eq $rule) { "
            "[pscustomobject]@{Configured=$false;Exists=$false} | ConvertTo-Json -Compress; exit }; "
            "$port=$rule | Get-NetFirewallPortFilter; "
            "$address=$rule | Get-NetFirewallAddressFilter; "
            "$profileValue=[uint32]$rule.Profile; "
            "$configured=(($rule.Enabled.ToString() -eq 'True') -and "
            "($rule.Direction.ToString() -eq 'Inbound') -and "
            "($rule.Action.ToString() -eq 'Allow') -and "
            f"($profileValue -eq {WINDOWS_FIREWALL_PRIVATE_PROFILE}) -and "
            "(($port.Protocol.ToString() -eq 'TCP') -or ([uint16]$port.Protocol -eq 6)) -and "
            "(@($port.LocalPort) -contains '8443') -and "
            "(@($address.RemoteAddress) -contains 'LocalSubnet')); "
            "[pscustomobject]@{Configured=$configured;Exists=$true;"
            "ProfileValue=$profileValue;Protocol=$port.Protocol.ToString();"
            "LocalPort=@($port.LocalPort);RemoteAddress=@($address.RemoteAddress)} | "
            "ConvertTo-Json -Compress"
        )
        result = await self.runner.run(
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
            timeout_seconds=self.settings.powershell_timeout_seconds,
        )
        if result.returncode != 0:
            return {
                "configured": False,
                "detail": "Не удалось прочитать правило Windows Firewall.",
            }
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "configured": False,
                "detail": "Windows вернула некорректные данные Firewall.",
            }
        configured = isinstance(payload, dict) and payload.get("Configured") is True
        return {
            "configured": configured,
            "detail": (
                "Правило TCP 8443 ограничено Private и LocalSubnet."
                if configured
                else "Точное правило TCP 8443 для Private и LocalSubnet не найдено."
            ),
            "rule": WINDOWS_ACADEMY_FIREWALL_RULE,
            "properties": payload if isinstance(payload, dict) else {},
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
