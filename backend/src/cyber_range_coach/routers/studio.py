from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import select

from ..errors import AppError
from ..models import Draft, StudioSource
from ..schemas import DraftCreate, DraftResponse, DraftUpdate, StudioSourceResponse
from ..security import Principal, require_role
from ..services.migration import import_v1_notes
from ..services.studio import (
    create_draft,
    draft_response,
    import_source,
    publish_draft,
    studio_source_response,
    update_draft,
    validate_draft,
)

router = APIRouter(prefix="/api/v2/studio", tags=["studio"])


@router.post("/import", response_model=StudioSourceResponse, status_code=201)
async def upload_source(
    request: Request,
    file: UploadFile = File(...),
    _principal: Principal = Depends(require_role("owner")),
) -> StudioSourceResponse:
    with request.app.state.db.session_factory() as session:
        return await import_source(session, request.app.state.settings, file)


@router.get("/sources", response_model=list[StudioSourceResponse])
def sources(
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> list[StudioSourceResponse]:
    with request.app.state.db.session_factory() as session:
        items = session.scalars(select(StudioSource).order_by(StudioSource.created_at.desc())).all()
        return [studio_source_response(session, item) for item in items]


@router.post("/drafts", response_model=DraftResponse, status_code=201)
def new_draft(
    payload: DraftCreate,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> DraftResponse:
    with request.app.state.db.session_factory() as session:
        return draft_response(create_draft(session, payload.title, payload.source_ids))


@router.get("/drafts", response_model=list[DraftResponse])
def drafts(
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> list[DraftResponse]:
    with request.app.state.db.session_factory() as session:
        items = session.scalars(select(Draft).order_by(Draft.created_at.desc())).all()
        return [draft_response(item) for item in items]


@router.put("/drafts/{draft_id}", response_model=DraftResponse)
def edit_draft(
    draft_id: int,
    payload: DraftUpdate,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> DraftResponse:
    with request.app.state.db.session_factory() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise AppError(404, "draft_not_found", "Studio draft не найден.")
        return draft_response(update_draft(session, draft, payload.title, payload.content))


@router.post("/drafts/{draft_id}/validate", response_model=DraftResponse)
def validate(
    draft_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> DraftResponse:
    with request.app.state.db.session_factory() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise AppError(404, "draft_not_found", "Studio draft не найден.")
        validate_draft(session, request.app.state.settings, draft)
        session.refresh(draft)
        return draft_response(draft)


@router.post("/drafts/{draft_id}/publish", response_model=DraftResponse)
def publish(
    draft_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("owner")),
) -> DraftResponse:
    with request.app.state.db.session_factory() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise AppError(404, "draft_not_found", "Studio draft не найден.")
        return draft_response(publish_draft(session, request.app.state.settings, draft))


@router.post("/import-v1-notes")
async def import_notes_v1(
    request: Request,
    file: UploadFile = File(...),
    _principal: Principal = Depends(require_role("owner")),
) -> dict[str, int]:
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise AppError(413, "v1_export_too_large", "Экспорт заметок v1 неожиданно большой.")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AppError(422, "invalid_v1_export", "Экспорт v1 не является корректным JSON.") from exc
    with request.app.state.db.session_factory() as session:
        return import_v1_notes(session, payload)
