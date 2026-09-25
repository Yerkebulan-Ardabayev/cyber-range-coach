from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from ..config import project_root
from ..errors import AppError
from ..models import LinuxHost
from ..schemas import (
    FingerprintConfirm,
    LinuxHostCreate,
    LinuxHostResponse,
    LinuxProbeResponse,
    NetworkResponse,
    PreflightResponse,
    WslUbuntuPrepareResponse,
)
from ..security import Principal, require_role
from ..services.preflight import network_response
from ..services.secrets import SecretProtectionError
from ..services.ssh import create_linux_host_keypair, probe_linux_host
from ..services.wsl import prepare_wsl_ubuntu

router = APIRouter(prefix="/api/v2/system", tags=["system"])


@router.get("/linux-bootstrap/{filename}", response_class=FileResponse)
def linux_bootstrap_file(
    filename: str,
    _principal: Principal = Depends(require_role("owner")),
) -> FileResponse:
    allowed = {"bootstrap-linux.sh", "bootstrap-wsl-ubuntu.sh", "crc-range-check"}
    if filename not in allowed:
        raise AppError(404, "bootstrap_file_not_found", "Linux bootstrap file не найден.")
    path = project_root() / "installer" / "linux" / filename
    if not path.is_file():
        raise AppError(404, "bootstrap_file_not_found", "Linux bootstrap file не упакован.")
    return FileResponse(path, media_type="text/x-shellscript", filename=filename)


@router.get("/ca-certificate", response_class=FileResponse)
def ca_certificate(request: Request) -> FileResponse:
    path = request.app.state.settings.certificates_dir / "cyber-range-coach-ca.crt"
    if not path.exists():
        raise AppError(404, "ca_not_generated", "Локальный CA certificate ещё не создан.")
    return FileResponse(path, media_type="application/x-x509-ca-cert", filename=path.name)


@router.get("/preflight", response_model=PreflightResponse)
async def preflight(
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> PreflightResponse:
    return cast(PreflightResponse, await request.app.state.preflight.run())


@router.get("/network", response_model=NetworkResponse)
def network(
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> NetworkResponse:
    return network_response(request.app.state.settings)


@router.get("/linux-host", response_model=LinuxHostResponse | None)
def get_linux_host(
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> LinuxHostResponse | None:
    with request.app.state.db.session_factory() as session:
        host = session.scalars(select(LinuxHost).order_by(LinuxHost.id)).first()
        if host is None:
            return None
        return LinuxHostResponse.model_validate(
            {
                **{column.name: getattr(host, column.name) for column in host.__table__.columns},
                "confirmed": bool(host.confirmed_at and host.host_key),
            }
        )


@router.post("/linux-host", response_model=LinuxHostResponse)
def configure_linux_host(
    payload: LinuxHostCreate,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> LinuxHostResponse:
    protector = request.app.state.protector
    if protector is None:
        raise AppError(
            503,
            "secret_storage_unavailable",
            "На этом host недоступно защищённое хранилище SSH key.",
        )
    try:
        encrypted_key, public_key = create_linux_host_keypair(protector)
        encrypted_runner_key, runner_public_key = create_linux_host_keypair(protector)
    except SecretProtectionError as exc:
        raise AppError(503, "secret_storage_failed", "Не удалось защитить SSH key.") from exc
    with request.app.state.db.session_factory() as session:
        existing = session.scalars(select(LinuxHost).order_by(LinuxHost.id)).first()
        if existing is None:
            host = LinuxHost(
                **payload.model_dump(),
                encrypted_private_key=encrypted_key,
                public_key=public_key,
                encrypted_runner_private_key=encrypted_runner_key,
                runner_public_key=runner_public_key,
            )
            session.add(host)
        else:
            host = existing
            for key, value in payload.model_dump().items():
                setattr(host, key, value)
            host.encrypted_private_key = encrypted_key
            host.public_key = public_key
            host.encrypted_runner_private_key = encrypted_runner_key
            host.runner_public_key = runner_public_key
            host.pending_host_key = None
            host.host_key = None
            host.host_key_fingerprint = None
            host.confirmed_at = None
        session.commit()
        session.refresh(host)
        return LinuxHostResponse.model_validate(
            {
                **{column.name: getattr(host, column.name) for column in host.__table__.columns},
                "confirmed": False,
            }
        )


@router.post("/linux-host/{host_id}/probe", response_model=LinuxProbeResponse)
async def probe(
    host_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> LinuxProbeResponse:
    protector = request.app.state.protector
    if protector is None:
        raise AppError(503, "secret_storage_unavailable", "SSH secret storage недоступно.")
    with request.app.state.db.session_factory() as session:
        host = session.get(LinuxHost, host_id)
        if host is None:
            raise AppError(404, "linux_host_not_found", "Linux VM profile не найден.")
        session.expunge(host)
    result = await probe_linux_host(
        host,
        protector,
        request.app.state.settings.ssh_connect_timeout_seconds,
        request.app.state.wsl_keepalive.ensure,
    )
    if result.ssh_authenticated and result.host_key:
        with request.app.state.db.session_factory() as session:
            stored = session.get(LinuxHost, host_id)
            if stored:
                stored.pending_host_key = result.host_key
                stored.last_preflight_at = datetime.now(UTC)
                session.commit()
    return result


@router.post(
    "/linux-host/{host_id}/wsl-ubuntu/prepare",
    response_model=WslUbuntuPrepareResponse,
)
async def prepare_wsl(
    host_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> WslUbuntuPrepareResponse:
    with request.app.state.db.session_factory() as session:
        host = session.get(LinuxHost, host_id)
        if host is None:
            raise AppError(404, "linux_host_not_found", "Linux VM profile не найден.")
        session.expunge(host)
    result = await prepare_wsl_ubuntu(
        request.app.state.settings,
        request.app.state.runner,
        host,
    )
    if result.relay_source_ip:
        with request.app.state.db.session_factory() as session:
            stored = session.get(LinuxHost, host_id)
            if stored:
                stored.relay_source_ip = result.relay_source_ip
                session.commit()
    return result


@router.post("/linux-host/{host_id}/confirm", response_model=LinuxHostResponse)
def confirm_host_key(
    host_id: int,
    payload: FingerprintConfirm,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> LinuxHostResponse:
    import asyncssh

    with request.app.state.db.session_factory() as session:
        host = session.get(LinuxHost, host_id)
        if host is None or not host.pending_host_key:
            raise AppError(409, "host_key_not_probed", "Сначала выполните SSH probe.")
        key = asyncssh.import_public_key(host.pending_host_key)
        actual = key.get_fingerprint()
        if payload.fingerprint != actual:
            raise AppError(
                409,
                "host_fingerprint_mismatch",
                "Подтверждённый fingerprint не совпадает с последним SSH probe.",
                {"expected": actual},
            )
        host.host_key = host.pending_host_key
        host.pending_host_key = None
        host.host_key_fingerprint = actual
        host.confirmed_at = datetime.now(UTC)
        session.commit()
        session.refresh(host)
        return LinuxHostResponse.model_validate(
            {
                **{column.name: getattr(host, column.name) for column in host.__table__.columns},
                "confirmed": True,
            }
        )


@router.post("/linux-host/{host_id}/runner-check")
async def runner_check(
    host_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> dict[str, object]:
    with request.app.state.db.session_factory() as session:
        host = session.get(LinuxHost, host_id)
        if host is None:
            raise AppError(404, "linux_host_not_found", "Linux VM profile не найден.")
    return cast(dict[str, object], await request.app.state.range_runner.tools())


@router.post("/ai/codex/isolation-probe")
async def probe_codex_isolation(
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> dict[str, object]:
    return cast(dict[str, object], await request.app.state.ai.codex.probe_isolation())


@router.post("/ai/claude/isolation-probe")
async def probe_claude_isolation(
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> dict[str, object]:
    return cast(dict[str, object], await request.app.state.ai.claude.probe_isolation())
