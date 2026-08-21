from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from ..errors import AppError
from ..models import LinuxHost, TargetProfile
from ..schemas import (
    DiscoveredTarget,
    RelayResponse,
    RelayStartRequest,
    TargetCreate,
    TargetResponse,
    TargetVerifyResponse,
)
from ..security import Principal, require_role
from ..services.network import local_interfaces, verify_target
from ..services.relay import configured_relay_source_ip

router = APIRouter(prefix="/api/v2/targets", tags=["targets"])


def _target_response(target: TargetProfile) -> TargetResponse:
    return TargetResponse.model_validate(target)


def _connect_host(request: Request) -> str:
    configured = request.app.state.settings.relay_advertised_host
    if configured:
        return cast(str, configured)
    candidates = [
        item.address
        for item in local_interfaces()
        if item.private and not item.loopback and ":" not in item.address
    ]
    if not candidates:
        raise AppError(
            409,
            "relay_host_unknown",
            "Не удалось определить Windows IP для Linux VM. Укажите CRC_RELAY_ADVERTISED_HOST.",
        )
    return candidates[0]


@router.get("/discover", response_model=list[DiscoveredTarget])
async def discover(
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> list[DiscoveredTarget]:
    return cast(list[DiscoveredTarget], await request.app.state.docker.discover())


@router.get("", response_model=list[TargetResponse])
def list_targets(
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> list[TargetResponse]:
    with request.app.state.db.session_factory() as session:
        targets = session.scalars(select(TargetProfile).order_by(TargetProfile.display_name)).all()
        return [_target_response(target) for target in targets]


@router.post("", response_model=TargetResponse, status_code=201)
async def create_target(
    payload: TargetCreate,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> TargetResponse:
    binding = await request.app.state.docker.resolve_binding(
        payload.container_id, payload.container_port, payload.protocol
    )
    if binding.port.loopback_endpoint is None:
        raise AppError(
            400, "tcp_binding_required", "Training Relay поддерживает только TCP binding."
        )
    fingerprint = request.app.state.docker.fingerprint(binding.container, binding.port)
    health_path = "/WebGoat/" if binding.container.detected_kind == "webgoat" else "/"
    endpoint = binding.port.loopback_endpoint.rstrip("/") + health_path
    warnings = list(binding.container.warnings)
    with request.app.state.db.session_factory() as session:
        existing = session.scalar(
            select(TargetProfile).where(
                TargetProfile.container_reference == binding.container.container_id,
                TargetProfile.container_port == binding.port.container_port,
            )
        )
        if existing:
            raise AppError(
                409,
                "target_already_registered",
                "Этот контейнер уже зарегистрирован как учебная цель.",
                {"target_id": existing.id},
            )
        target = TargetProfile(
            display_name=payload.display_name,
            provider="docker_desktop",
            container_reference=binding.container.container_id,
            container_port=binding.port.container_port,
            image_digest=binding.container.image_digest,
            host_endpoint=endpoint,
            health_check={"type": "http", "path": health_path, "verify_tls": True},
            reset_policy="external",
            fingerprint=fingerprint,
            allowed_curriculum_tags=payload.allowed_curriculum_tags,
            exposure_warnings=warnings,
        )
        session.add(target)
        session.commit()
        session.refresh(target)
        return _target_response(target)


@router.post("/{target_id}/verify", response_model=TargetVerifyResponse)
async def verify(
    target_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> TargetVerifyResponse:
    with request.app.state.db.session_factory() as session:
        target = session.get(TargetProfile, target_id)
        if target is None:
            raise AppError(404, "target_not_found", "Учебная цель не найдена.")
        session.expunge(target)
    result = await verify_target(target)
    with request.app.state.db.session_factory() as session:
        stored = session.get(TargetProfile, target_id)
        if stored and result.reachable:
            stored.last_verified_at = datetime.now(UTC)
            session.commit()
    return result


@router.post("/{target_id}/relay/start", response_model=RelayResponse)
async def start_relay(
    target_id: int,
    payload: RelayStartRequest,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> RelayResponse:
    with request.app.state.db.session_factory() as session:
        target = session.get(TargetProfile, target_id)
        linux_host = session.scalars(select(LinuxHost).order_by(LinuxHost.id)).first()
        if target is None:
            raise AppError(404, "target_not_found", "Учебная цель не найдена.")
        if linux_host is None:
            raise AppError(409, "vm_ip_mismatch", "Relay разрешён только для настроенной Linux VM.")
        relay_source_ip = configured_relay_source_ip(linux_host)
        if payload.linux_vm_ip != relay_source_ip:
            raise AppError(409, "vm_ip_mismatch", "Relay разрешён только для настроенной Linux VM.")
        session.expunge(target)
    parsed = urlparse(target.host_endpoint)
    upstream_host = parsed.hostname or "127.0.0.1"
    upstream_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    handle = await request.app.state.relays.start(
        target.id, upstream_host, upstream_port, relay_source_ip
    )
    try:
        runner_check = await request.app.state.range_runner.relay(handle.port)
    except Exception:
        await request.app.state.relays.stop(target.id)
        raise
    if not runner_check.get("reachable"):
        await request.app.state.relays.stop(target.id)
        raise AppError(
            409,
            "relay_not_reachable_from_vm",
            "Linux VM не смогла подключиться к временному Training Relay.",
            runner_check,
        )
    return RelayResponse(
        target_id=target.id,
        active=True,
        bind_host=handle.bind_host,
        connect_host=_connect_host(request),
        port=handle.port,
        allowed_source_ip=handle.allowed_source_ip,
        upstream=f"{handle.upstream_host}:{handle.upstream_port}",
    )


@router.post("/{target_id}/relay/stop", response_model=RelayResponse)
async def stop_relay(
    target_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> RelayResponse:
    await request.app.state.relays.stop(target_id)
    return RelayResponse(target_id=target_id, active=False)
