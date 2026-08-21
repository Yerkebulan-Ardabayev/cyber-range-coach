from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update

from ..errors import AppError
from ..models import Device, PairingCode
from ..schemas import (
    PairedDevice,
    PairingConsume,
    PairingCreate,
    PairingCreated,
    PairingResult,
)
from ..security import Principal, hash_token, new_token, require_role
from ..services.tls import certificate_fingerprint

router = APIRouter(prefix="/api/v2/devices", tags=["devices"])


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.post("/pairing-codes", response_model=PairingCreated, status_code=201)
async def create_pairing_code(
    payload: PairingCreate,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> PairingCreated:
    preflight = await request.app.state.preflight.run()
    settings = request.app.state.settings
    if not settings.lan_mode or not settings.tls_enabled or not preflight.ready:
        raise AppError(
            409,
            "pairing_preflight_incomplete",
            "Привязка устройств доступна только после полного HTTPS preflight в LAN mode.",
        )
    token = new_token()
    expires = datetime.now(UTC) + timedelta(seconds=settings.pairing_ttl_seconds)
    with request.app.state.db.session_factory() as session:
        session.add(
            PairingCode(
                token_hash=hash_token(token),
                requested_role=payload.role,
                expires_at=expires,
            )
        )
        session.commit()
    return PairingCreated(
        token=token,
        role=payload.role,
        expires_at=expires,
        certificate_fingerprint=certificate_fingerprint(settings),
    )


@router.post("/pair", response_model=PairingResult)
def pair_device(payload: PairingConsume, request: Request, response: Response) -> PairingResult:
    expected_fingerprint = certificate_fingerprint(request.app.state.settings)
    if not hmac.compare_digest(payload.confirmed_fingerprint, expected_fingerprint):
        raise AppError(
            409,
            "certificate_fingerprint_mismatch",
            "Fingerprint сертификата не совпадает с экраном владельца.",
        )
    token_hash = hash_token(payload.token)
    with request.app.state.db.session_factory() as session:
        now = datetime.now(UTC)
        pairing = session.scalar(select(PairingCode).where(PairingCode.token_hash == token_hash))
        if pairing is None or _aware(pairing.expires_at) <= now:
            raise AppError(
                410, "pairing_code_expired", "Pairing token недействителен или уже использован."
            )
        consumed = session.execute(
            update(PairingCode)
            .where(
                PairingCode.id == pairing.id,
                PairingCode.consumed_at.is_(None),
                PairingCode.expires_at > now,
            )
            .values(consumed_at=now)
            .execution_options(synchronize_session=False)
        )
        if consumed.rowcount != 1:
            session.rollback()
            raise AppError(
                410, "pairing_code_expired", "Pairing token недействителен или уже использован."
            )
        device_secret = new_token()
        csrf_token = new_token()
        device = Device(
            name=payload.device_name,
            role=pairing.requested_role,
            token_hash=hash_token(device_secret),
        )
        session.add(device)
        session.commit()
        session.refresh(device)
        cookie_value = f"{device.id}.{device_secret}"
        secure = request.app.state.settings.tls_enabled
        response.set_cookie(
            request.app.state.settings.session_cookie_name,
            cookie_value,
            httponly=True,
            secure=secure,
            samesite="strict",
            max_age=90 * 24 * 60 * 60,
            path="/",
        )
        response.set_cookie(
            request.app.state.settings.csrf_cookie_name,
            csrf_token,
            httponly=False,
            secure=secure,
            samesite="strict",
            max_age=90 * 24 * 60 * 60,
            path="/",
        )
        return PairingResult(device=PairedDevice.model_validate(device), csrf_token=csrf_token)


@router.get("", response_model=list[PairedDevice])
def list_devices(
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> list[PairedDevice]:
    with request.app.state.db.session_factory() as session:
        items = session.scalars(select(Device).order_by(Device.created_at.desc())).all()
        return [PairedDevice.model_validate(item) for item in items]


@router.get("/me")
def me(
    request: Request,
    response: Response,
    principal: Principal = Depends(require_role("viewer")),
) -> dict[str, object]:
    if principal.local_owner and not request.cookies.get(
        request.app.state.settings.csrf_cookie_name
    ):
        response.set_cookie(
            request.app.state.settings.csrf_cookie_name,
            new_token(),
            httponly=False,
            secure=request.app.state.settings.tls_enabled,
            samesite="strict",
            path="/",
        )
    return {
        "role": principal.role,
        "device_id": principal.device_id,
        "local_owner": principal.local_owner,
    }


@router.post("/{device_id}/revoke", response_model=PairedDevice)
def revoke_device(
    device_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> PairedDevice:
    with request.app.state.db.session_factory() as session:
        device = session.get(Device, device_id)
        if device is None:
            raise AppError(404, "device_not_found", "Устройство не найдено.")
        device.revoked_at = datetime.now(UTC)
        session.commit()
        session.refresh(device)
        return PairedDevice.model_validate(device)
