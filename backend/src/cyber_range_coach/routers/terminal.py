from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..errors import AppError
from ..security import ROLE_LEVEL, websocket_principal
from .learning import ensure_run_relay

router = APIRouter(tags=["terminal"])


def _same_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not origin or not host:
        return False
    return urlparse(origin).netloc.lower() == host.lower()


@router.websocket("/api/v2/terminal/{run_id}")
async def terminal(websocket: WebSocket, run_id: int) -> None:
    principal = websocket_principal(websocket)
    if principal is None:
        await websocket.close(code=4401, reason="устройство не привязано")
        return
    if ROLE_LEVEL[principal.role] < ROLE_LEVEL["operator"]:
        await websocket.close(code=4403, reason="роль viewer не может открыть терминал")
        return
    if not _same_origin(websocket):
        await websocket.close(code=4403, reason="origin WebSocket не совпадает")
        return
    await websocket.accept()
    try:
        await ensure_run_relay(websocket, run_id)
    except AppError as exc:
        await websocket.send_json(
            {"type": "error", "message": f"Связь с учебной целью не восстановлена: {exc.message}"}
        )
    try:
        terminal_session = await websocket.app.state.terminals.get_or_start(run_id)
    except Exception:
        await websocket.send_json(
            {"type": "error", "message": "Терминал не удалось открыть. Сначала выполните проверку SSH."}
        )
        await websocket.close(code=1011)
        return
    await terminal_session.attach(websocket)
    try:
        while True:
            payload = await websocket.receive_json()
            kind = payload.get("type")
            if kind == "input":
                data = str(payload.get("data", ""))
                if len(data.encode("utf-8")) > 16_384:
                    await websocket.send_json(
                        {"type": "error", "message": "Входной кадр слишком большой."}
                    )
                    continue
                await terminal_session.input(data)
            elif kind == "resize":
                columns = max(20, min(400, int(payload.get("cols", 120))))
                rows = max(5, min(200, int(payload.get("rows", 32))))
                terminal_session.resize(columns, rows)
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "error", "message": "Неизвестный кадр терминала."})
    except WebSocketDisconnect:
        terminal_session.detach(
            websocket, websocket.app.state.settings.terminal_reconnect_grace_seconds
        )
