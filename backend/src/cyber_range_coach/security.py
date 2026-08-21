from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import Depends, Request, WebSocket
from sqlalchemy.orm import Session

from .errors import AppError
from .models import Device, DeviceRole

RoleName = Literal["owner", "operator", "viewer"]
ROLE_LEVEL: dict[str, int] = {"viewer": 1, "operator": 2, "owner": 3}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Principal:
    role: RoleName
    device_id: int | None
    local_owner: bool = False


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return False
    normalized = host.split("%", maxsplit=1)[0]
    return normalized in {"127.0.0.1", "::1", "testclient"}


def _device_from_cookie(session: Session, cookie: str | None) -> Device | None:
    if not cookie or "." not in cookie:
        return None
    raw_id, token = cookie.split(".", maxsplit=1)
    if not raw_id.isdigit() or not token:
        return None
    device = session.get(Device, int(raw_id))
    if device is None or device.revoked_at is not None:
        return None
    if not hmac.compare_digest(device.token_hash, hash_token(token)):
        return None
    device.last_seen_at = datetime.now(UTC)
    session.commit()
    return device


def authenticate_request(request: Request, session: Session) -> Principal:
    settings = request.app.state.settings
    if settings.testing and settings.allow_test_role_header:
        test_role = request.headers.get("x-test-role")
        if test_role in ROLE_LEVEL:
            return Principal(role=cast(RoleName, test_role), device_id=None)
    client_host = request.client.host if request.client else None
    if _is_loopback(client_host):
        return Principal(role=DeviceRole.owner.value, device_id=None, local_owner=True)
    device = _device_from_cookie(session, request.cookies.get(settings.session_cookie_name))
    if device is None:
        raise AppError(401, "authentication_required", "Устройство не привязано к академии.")
    return Principal(role=cast(RoleName, device.role), device_id=device.id)


def require_role(minimum: RoleName) -> Callable[[Request], Principal]:
    def dependency(request: Request) -> Principal:
        with request.app.state.db.session_factory() as session:
            principal = authenticate_request(request, session)
        if ROLE_LEVEL[principal.role] < ROLE_LEVEL[minimum]:
            raise AppError(403, "role_forbidden", "Роль устройства не разрешает это действие.")
        if request.method not in SAFE_METHODS:
            csrf_cookie = request.cookies.get(request.app.state.settings.csrf_cookie_name)
            csrf_header = request.headers.get("x-csrf-token")
            if (
                not csrf_cookie
                or not csrf_header
                or not hmac.compare_digest(csrf_cookie, csrf_header)
            ):
                raise AppError(403, "csrf_failed", "Проверка безопасности запроса не пройдена.")
        return principal

    return dependency


def current_principal(request: Request) -> Principal:
    with request.app.state.db.session_factory() as session:
        return authenticate_request(request, session)


def websocket_principal(websocket: WebSocket) -> Principal | None:
    settings = websocket.app.state.settings
    if settings.testing and settings.allow_test_role_header:
        test_role = websocket.headers.get("x-test-role")
        if test_role in ROLE_LEVEL:
            return Principal(role=cast(RoleName, test_role), device_id=None)
    client_host = websocket.client.host if websocket.client else None
    if _is_loopback(client_host):
        return Principal(role="owner", device_id=None, local_owner=True)
    cookie = websocket.cookies.get(settings.session_cookie_name)
    with websocket.app.state.db.session_factory() as session:
        device = _device_from_cookie(session, cookie)
    if device is None:
        return None
    return Principal(role=cast(RoleName, device.role), device_id=device.id)


Owner = Depends(require_role("owner"))
Operator = Depends(require_role("operator"))
Viewer = Depends(require_role("viewer"))
