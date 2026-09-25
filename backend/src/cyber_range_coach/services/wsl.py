from __future__ import annotations

import ipaddress
import shlex
import sys
from pathlib import Path

from ..config import Settings, project_root
from ..database import Database
from ..models import LinuxHost
from ..schemas import WslUbuntuPrepareResponse
from .commands import SafeCommandRunner
from .network import tcp_connect
from .relay import configured_relay_source_ip, validate_relay_source_ip

WSL_STAGE_DIRECTORY = ".local/share/cyber-range-coach"
WSL_FILES = ("bootstrap-linux.sh", "bootstrap-wsl-ubuntu.sh", "crc-range-check")


def normalize_wsl_output(value: str) -> str:
    """Normalize wsl.exe output from both UTF-8 and legacy UTF-16-style pipes."""
    return value.replace("\x00", "").replace("\r", "").strip()


def select_ubuntu_distribution(output: str) -> str | None:
    distributions = [line.strip() for line in normalize_wsl_output(output).splitlines()]
    distributions = [line for line in distributions if line]
    if "Ubuntu" in distributions:
        return "Ubuntu"
    return next((name for name in distributions if name.casefold().startswith("ubuntu")), None)


def select_wsl_source_ip(output: str) -> str | None:
    for candidate in normalize_wsl_output(output).split():
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.version == 4 and not (
            address.is_loopback or address.is_unspecified or address.is_multicast
        ):
            return str(address)
    return None


def load_wsl_files(directory: Path) -> dict[str, str] | None:
    sources: dict[str, str] = {}
    for filename in WSL_FILES:
        source = directory / filename
        if not source.is_file():
            return None
        sources[filename] = source.read_text(encoding="utf-8")
    return sources


async def current_wsl_source_ip(
    runner: SafeCommandRunner,
    timeout_seconds: float,
    *,
    start_if_stopped: bool = False,
) -> tuple[str | None, str | None]:
    listed = await runner.run(
        "wsl.exe", "--list", "--quiet", timeout_seconds=timeout_seconds
    )
    distribution = select_ubuntu_distribution(listed.stdout) if listed.returncode == 0 else None
    if distribution is None:
        return None, None
    if not start_if_stopped:
        running = await runner.run(
            "wsl.exe",
            "--list",
            "--running",
            "--quiet",
            timeout_seconds=timeout_seconds,
        )
        running_distributions = {
            line.strip()
            for line in normalize_wsl_output(running.stdout).splitlines()
            if line.strip()
        }
        if running.returncode != 0 or distribution not in running_distributions:
            return distribution, None
    source_result = await runner.run(
        "wsl.exe",
        "--distribution",
        distribution,
        "--exec",
        "hostname",
        "-I",
        timeout_seconds=timeout_seconds,
    )
    relay_source_ip = (
        select_wsl_source_ip(source_result.stdout) if source_result.returncode == 0 else None
    )
    return distribution, relay_source_ip


def follows_wsl_address(host: LinuxHost) -> bool:
    """WSL on Windows is reached by SSH on loopback and gets a new NAT address on every boot."""
    return sys.platform == "win32" and host.host == "127.0.0.1"


def acceptable_wsl_source_ip(value: str | None) -> str | None:
    if not value:
        return None
    address = ipaddress.ip_address(value)
    return str(address) if address.version == 4 and address.is_private and not address.is_loopback else None


async def relay_source_ip_for_start(
    database: Database,
    runner: SafeCommandRunner,
    timeout_seconds: float,
    host: LinuxHost,
) -> str:
    """Source address the relay must accept for this start (spec 11.3 Zh).

    For WSL the live address comes from wsl.exe on this machine and is saved, so
    a reboot needs no owner action; the relay firewall rule is bound to the WSL
    adapter, not to the address. Other Linux VMs keep their configured address.
    """
    if not follows_wsl_address(host):
        return configured_relay_source_ip(host)
    _, current = await current_wsl_source_ip(runner, timeout_seconds, start_if_stopped=True)
    accepted = acceptable_wsl_source_ip(current)
    if accepted is None:
        return configured_relay_source_ip(host)
    if accepted != host.relay_source_ip:
        with database.session_factory() as session:
            stored = session.get(LinuxHost, host.id)
            if stored is not None:
                stored.relay_source_ip = accepted
                session.commit()
        host.relay_source_ip = accepted
    return validate_relay_source_ip(accepted)


def _manual_sudo_command(
    stage_directory: str,
    host: LinuxHost,
    relay_host: str,
) -> str:
    arguments = [
        "sudo",
        "bash",
        f"{stage_directory}/bootstrap-wsl-ubuntu.sh",
        "--approve-install",
        "--student-user",
        host.username,
        "--runner-user",
        host.runner_username,
        "--student-key",
        host.public_key,
        "--runner-key",
        host.runner_public_key,
        "--relay-host",
        relay_host,
    ]
    return "cd " + shlex.quote(stage_directory) + " && " + shlex.join(arguments)


async def _stage_file(
    runner: SafeCommandRunner,
    distribution: str,
    filename: str,
    source: str,
) -> bool:
    command = (
        f'umask 077; install -d -m 700 "$HOME/{WSL_STAGE_DIRECTORY}"; '
        f'cat > "$HOME/{WSL_STAGE_DIRECTORY}/{filename}"; '
        f'chmod 700 "$HOME/{WSL_STAGE_DIRECTORY}/{filename}"'
    )
    result = await runner.run(
        "wsl.exe",
        "--distribution",
        distribution,
        "--exec",
        "sh",
        "-c",
        command,
        stdin=source,
        timeout_seconds=30,
    )
    return result.returncode == 0


async def prepare_wsl_ubuntu(
    settings: Settings,
    runner: SafeCommandRunner,
    host: LinuxHost,
) -> WslUbuntuPrepareResponse:
    if sys.platform != "win32":
        return WslUbuntuPrepareResponse(
            status="blocked",
            distribution=None,
            host="127.0.0.1",
            port=22,
            ssh_reachable=False,
            detail="Готовый мастер WSL Ubuntu запускается только на Windows.",
        )
    expected = (host.host, host.port, host.username, host.runner_username)
    if expected != ("127.0.0.1", 22, "student", "range-runner"):
        return WslUbuntuPrepareResponse(
            status="blocked",
            distribution=None,
            host="127.0.0.1",
            port=22,
            ssh_reachable=False,
            detail="Профиль WSL должен использовать 127.0.0.1:22, student и range-runner.",
        )

    distribution, relay_source_ip = await current_wsl_source_ip(
        runner, settings.subprocess_timeout_seconds, start_if_stopped=True
    )
    if distribution is None:
        return WslUbuntuPrepareResponse(
            status="blocked",
            distribution=None,
            host=host.host,
            port=host.port,
            ssh_reachable=False,
            detail="Дистрибутив Ubuntu в WSL не найден. Установите или запустите Ubuntu и повторите.",
        )

    linux_installer = project_root() / "installer" / "linux"
    sources = load_wsl_files(linux_installer)
    if sources is None:
        return WslUbuntuPrepareResponse(
            status="blocked",
            distribution=distribution,
            host=host.host,
            port=host.port,
            ssh_reachable=False,
            detail="Комплект WSL bootstrap не упакован полностью.",
        )
    for filename, source in sources.items():
        if not await _stage_file(runner, distribution, filename, source):
            return WslUbuntuPrepareResponse(
                status="blocked",
                distribution=distribution,
                host=host.host,
                port=host.port,
                ssh_reachable=False,
                detail=f"Не удалось безопасно подготовить {filename} внутри WSL Ubuntu.",
            )

    home_result = await runner.run(
        "wsl.exe",
        "--distribution",
        distribution,
        "--exec",
        "sh",
        "-c",
        'printf %s "$HOME"',
    )
    home = normalize_wsl_output(home_result.stdout)
    if home_result.returncode != 0 or not home.startswith("/") or "\n" in home:
        return WslUbuntuPrepareResponse(
            status="blocked",
            distribution=distribution,
            host=host.host,
            port=host.port,
            ssh_reachable=False,
            detail="Не удалось определить домашний каталог пользователя Ubuntu.",
        )
    stage_directory = f"{home}/{WSL_STAGE_DIRECTORY}"

    if relay_source_ip is None:
        return WslUbuntuPrepareResponse(
            status="blocked",
            distribution=distribution,
            host=host.host,
            port=host.port,
            ssh_reachable=False,
            detail="WSL не вернула фактический IPv4 source address для Training Relay.",
        )

    relay_result = await runner.run(
        "wsl.exe",
        "--distribution",
        distribution,
        "--exec",
        "sh",
        "-c",
        "ip route show default | awk 'NR == 1 { print $3 }'",
    )
    relay_host = normalize_wsl_output(relay_result.stdout)
    try:
        relay_address = ipaddress.ip_address(relay_host)
    except ValueError:
        relay_address = None
    if relay_result.returncode != 0 or relay_address is None or relay_address.version != 4:
        return WslUbuntuPrepareResponse(
            status="blocked",
            distribution=distribution,
            host=host.host,
            port=host.port,
            relay_source_ip=relay_source_ip,
            ssh_reachable=False,
            detail="WSL не смог определить IPv4-адрес Windows для Training Relay.",
        )

    sudo_command = _manual_sudo_command(stage_directory, host, relay_host)
    sudo_probe = await runner.run(
        "wsl.exe",
        "--distribution",
        distribution,
        "--exec",
        "sudo",
        "-n",
        "true",
    )
    if sudo_probe.returncode != 0:
        return WslUbuntuPrepareResponse(
            status="sudo_password_required",
            distribution=distribution,
            host=host.host,
            port=host.port,
            relay_source_ip=relay_source_ip,
            ssh_reachable=False,
            sudo_command=sudo_command,
            detail=(
                "Файлы и SSH-ключи подготовлены. Откройте Ubuntu, выполните показанную команду "
                "и введите sudo-пароль вашего обычного пользователя Ubuntu. Академия пароль не "
                "запрашивает и не сохраняет."
            ),
        )

    setup = await runner.run(
        "wsl.exe",
        "--distribution",
        distribution,
        "--exec",
        "sudo",
        "-n",
        "bash",
        f"{stage_directory}/bootstrap-wsl-ubuntu.sh",
        "--approve-install",
        "--student-user",
        host.username,
        "--runner-user",
        host.runner_username,
        "--student-key",
        host.public_key,
        "--runner-key",
        host.runner_public_key,
        "--relay-host",
        relay_host,
        timeout_seconds=300,
    )
    if setup.returncode != 0:
        return WslUbuntuPrepareResponse(
            status="blocked",
            distribution=distribution,
            host=host.host,
            port=host.port,
            relay_source_ip=relay_source_ip,
            ssh_reachable=False,
            sudo_command=sudo_command,
            detail="WSL Ubuntu bootstrap завершился с ошибкой. Откройте Ubuntu и выполните команду вручную.",
        )
    reachable, detail = await tcp_connect(host.host, host.port, settings.ssh_connect_timeout_seconds)
    return WslUbuntuPrepareResponse(
        status="ready_for_probe" if reachable else "blocked",
        distribution=distribution,
        host=host.host,
        port=host.port,
        relay_source_ip=relay_source_ip,
        ssh_reachable=reachable,
        sudo_command=None if reachable else sudo_command,
        detail=(
            "OpenSSH и обе учебные роли готовы. Теперь проверьте SSH и подтвердите fingerprint."
            if reachable
            else f"Bootstrap выполнен, но SSH на 127.0.0.1:22 пока недоступен: {detail}"
        ),
    )
