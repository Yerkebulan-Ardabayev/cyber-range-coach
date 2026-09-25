from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol, cast

from ..errors import AppError
from ..schemas import DiscoveredTarget, PublishedPort
from .commands import CommandResult


class DockerCommandRunner(Protocol):
    async def run(self, executable: str, *args: str) -> CommandResult: ...


CONTAINER_ID = re.compile(r"^[0-9a-fA-F]{12,64}$")


@dataclass(frozen=True)
class ResolvedBinding:
    container: DiscoveredTarget
    port: PublishedPort


class DockerDiscovery:
    def __init__(self, runner: DockerCommandRunner):
        self.runner = runner

    async def available(self) -> tuple[bool, str]:
        result = await self.runner.run("docker", "version", "--format", "{{json .Server}}")
        if result.returncode == 124:
            return False, "Docker CLI не ответил за отведённое время (docker version)."
        if result.returncode != 0:
            reason = (result.stderr.strip() or result.stdout.strip()).splitlines()
            return False, "Docker Engine не отвечает: " + (reason[0][:300] if reason else f"код {result.returncode}")
        return True, "Docker Engine отвечает через локальный Docker CLI."

    async def context(self) -> dict[str, Any]:
        result = await self.runner.run("docker", "context", "inspect")
        if result.returncode != 0:
            return {"available": False, "detail": result.stderr.strip()}
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"available": False, "detail": "Docker context вернул некорректный JSON"}
        current = payload[0] if isinstance(payload, list) and payload else {}
        return {
            "available": True,
            "name": current.get("Name"),
            "description": current.get("Metadata", {}).get("Description"),
            "docker_endpoint": current.get("Endpoints", {}).get("docker", {}).get("Host"),
        }

    async def discover(self) -> list[DiscoveredTarget]:
        available, detail = await self.available()
        if not available:
            raise AppError(
                503, "docker_unavailable", "Docker Desktop недоступен.", {"detail": detail}
            )
        result = await self.runner.run("docker", "ps", "--no-trunc", "--format", "{{json .}}")
        if result.returncode != 0:
            raise AppError(
                503,
                "docker_discovery_failed",
                "Не удалось прочитать список контейнеров.",
                {"detail": result.stderr.strip()},
            )
        discovered: list[DiscoveredTarget] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                summary = json.loads(line)
            except json.JSONDecodeError:
                continue
            container_id = str(summary.get("ID", ""))
            if not CONTAINER_ID.fullmatch(container_id):
                continue
            inspect = await self._inspect(container_id)
            await self._read_published_ports(container_id)
            discovered.append(self._normalize(summary, inspect))
        return discovered

    async def _read_published_ports(self, container_id: str) -> str:
        """Run Docker's read-only port view as an independent discovery check."""
        if not CONTAINER_ID.fullmatch(container_id):
            raise AppError(400, "invalid_container_id", "Некорректный идентификатор контейнера.")
        result = await self.runner.run("docker", "port", container_id)
        if result.returncode != 0:
            raise AppError(
                502,
                "docker_port_failed",
                "Docker не смог подтвердить опубликованные порты контейнера.",
                {"container_id": container_id, "detail": result.stderr.strip()},
            )
        return result.stdout

    async def _inspect(self, container_id: str) -> dict[str, Any]:
        if not CONTAINER_ID.fullmatch(container_id):
            raise AppError(400, "invalid_container_id", "Некорректный идентификатор контейнера.")
        result = await self.runner.run("docker", "inspect", container_id)
        if result.returncode != 0:
            raise AppError(
                404,
                "container_not_found",
                "Контейнер исчез во время проверки.",
                {"container_id": container_id},
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AppError(502, "docker_invalid_json", "Docker вернул некорректный JSON.") from exc
        if not isinstance(payload, list) or not payload:
            raise AppError(404, "container_not_found", "Docker не вернул сведения о контейнере.")
        return cast(dict[str, Any], payload[0])

    @staticmethod
    def _normalize(summary: dict[str, Any], inspect: dict[str, Any]) -> DiscoveredTarget:
        image = str(inspect.get("Config", {}).get("Image") or summary.get("Image") or "unknown")
        lowered = f"{image} {summary.get('Names', '')}".lower()
        if "webgoat" in lowered:
            kind = "webgoat"
        elif "juice" in lowered or "bkimminich" in lowered:
            kind = "juice_shop"
        else:
            kind = "generic"
        ports: list[PublishedPort] = []
        warnings: list[str] = []
        raw_ports = inspect.get("NetworkSettings", {}).get("Ports", {}) or {}
        for container_key, bindings in raw_ports.items():
            try:
                port_text, protocol = str(container_key).split("/", maxsplit=1)
                container_port = int(port_text)
            except (ValueError, TypeError):
                continue
            for binding in bindings or []:
                host_ip = str(binding.get("HostIp") or "")
                try:
                    host_port = int(binding.get("HostPort"))
                except (ValueError, TypeError):
                    continue
                exposure = "loopback" if host_ip in {"127.0.0.1", "::1"} else "lan"
                if host_ip in {"0.0.0.0", "::"}:
                    warnings.append(
                        f"Порт {host_port} опубликован на всех интерфейсах. Проверьте Windows Firewall."
                    )
                scheme = "https" if container_port in {443, 8443} else "http"
                endpoint = f"{scheme}://127.0.0.1:{host_port}" if protocol == "tcp" else None
                ports.append(
                    PublishedPort(
                        container_port=container_port,
                        protocol=protocol if protocol in {"tcp", "udp"} else "tcp",
                        host_ip=host_ip,
                        host_port=host_port,
                        loopback_endpoint=endpoint,
                        exposure=exposure,
                    )
                )
        state = inspect.get("State", {})
        health = state.get("Health", {}).get("Status")
        image_digest = str(inspect.get("Image") or image)
        return DiscoveredTarget(
            container_id=str(inspect.get("Id") or summary.get("ID")),
            name=str(inspect.get("Name", "")).lstrip("/")
            or str(summary.get("Names") or "container"),
            image=image,
            image_digest=image_digest,
            state=str(state.get("Status") or summary.get("State") or "unknown"),
            health=str(health) if health else None,
            started_at=str(state.get("StartedAt")) if state.get("StartedAt") else None,
            ports=ports,
            detected_kind=kind,
            warnings=sorted(set(warnings)),
        )

    async def resolve_binding(
        self, container_id: str, container_port: int, protocol: str = "tcp"
    ) -> ResolvedBinding:
        matches = [
            item for item in await self.discover() if item.container_id.startswith(container_id)
        ]
        if len(matches) != 1:
            raise AppError(
                404,
                "container_not_found",
                "Контейнер не найден или идентификатор неоднозначен.",
                {"container_id": container_id},
            )
        container = matches[0]
        ports = [
            port
            for port in container.ports
            if port.container_port == container_port and port.protocol == protocol
        ]
        if len(ports) != 1:
            raise AppError(
                400,
                "port_not_published",
                "Выбранный порт контейнера не опубликован ровно один раз.",
                {
                    "container_port": container_port,
                    "available": [p.model_dump() for p in container.ports],
                },
            )
        return ResolvedBinding(container=container, port=ports[0])

    @staticmethod
    def fingerprint(container: DiscoveredTarget, port: PublishedPort) -> str:
        material = f"{container.image_digest}\0{port.container_port}/{port.protocol}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()
