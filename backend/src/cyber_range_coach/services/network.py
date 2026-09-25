from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from ..models import TargetProfile
from ..schemas import NetworkInterface, TargetVerifyResponse

logger = logging.getLogger(__name__)


def local_interfaces() -> list[NetworkInterface]:
    addresses: set[str] = {"127.0.0.1", "::1"}
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None):
            addresses.add(str(result[4][0]).split("%", maxsplit=1)[0])
    except OSError as exc:
        logger.debug("Local interface enumeration failed: %s", type(exc).__name__)
    interfaces: list[NetworkInterface] = []
    for address in sorted(addresses):
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        interfaces.append(
            NetworkInterface(
                address=address, private=parsed.is_private, loopback=parsed.is_loopback
            )
        )
    return interfaces


def source_address_toward(peer: str) -> str | None:
    """IPv4 of the interface the OS routes to peer through; no packet is sent."""
    try:
        if ipaddress.ip_address(peer).version != 4:
            return None
    except ValueError:
        return None
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((peer, 9))
        return str(probe.getsockname()[0])
    except OSError:
        return None
    finally:
        probe.close()


async def tcp_connect(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        del reader
        return True, "TCP-соединение установлено"
    except (OSError, TimeoutError) as exc:
        return False, f"TCP-соединение не установлено: {type(exc).__name__}"


async def verify_target(target: TargetProfile) -> TargetVerifyResponse:
    parsed = urlparse(target.host_endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    tcp_ok, tcp_detail = await tcp_connect(host, port)
    if not tcp_ok:
        return TargetVerifyResponse(
            target_id=target.id,
            reachable=False,
            tcp_connected=False,
            http_response_received=False,
            detail=tcp_detail,
            checked_at=datetime.now(UTC),
        )
    if parsed.scheme not in {"http", "https"}:
        return TargetVerifyResponse(
            target_id=target.id,
            reachable=True,
            tcp_connected=True,
            http_response_received=False,
            detail="TCP endpoint доступен, HTTP-запрос не выполнялся.",
            checked_at=datetime.now(UTC),
        )
    try:
        verify_tls = bool((target.health_check or {}).get("verify_tls", True))
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=4.0,
            verify=verify_tls,
        ) as client:
            response = await client.get(target.host_endpoint)
        return TargetVerifyResponse(
            target_id=target.id,
            reachable=True,
            tcp_connected=True,
            http_response_received=True,
            http_status=response.status_code,
            detail=f"Получен HTTP-ответ со статусом {response.status_code}.",
            checked_at=datetime.now(UTC),
        )
    except httpx.HTTPError as exc:
        return TargetVerifyResponse(
            target_id=target.id,
            reachable=False,
            tcp_connected=True,
            http_response_received=False,
            detail=f"TCP-соединение есть, но корректный HTTP-ответ не получен: {type(exc).__name__}",
            checked_at=datetime.now(UTC),
        )
