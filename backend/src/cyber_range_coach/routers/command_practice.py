from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import select

from ..errors import AppError
from ..models import CommandAttempt, CommandPracticeState
from ..schemas import CommandCompleteRequest, CommandDraftRequest, CommandHintRequest
from ..security import Principal, require_role
from ..services.command_practice import (
    CommandPracticePlan,
    CompletionResult,
    complete_command_attempt,
    plan_command_practice,
    reveal_command_hint,
    save_command_draft,
)

router = APIRouter(prefix="/api/v2", tags=["command-practice"])

ATTEMPT_KEY = Path(min_length=16, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")


@router.get("/command-practice/plan", response_model=CommandPracticePlan)
def command_practice_plan(
    request: Request,
    limit: int = Query(default=5, ge=1, le=10),
    available_minutes: int = Query(default=25, ge=5, le=90),
    _principal: Principal = Depends(require_role("viewer")),
) -> CommandPracticePlan:
    with request.app.state.db.session_factory() as session:
        return plan_command_practice(
            session,
            request.app.state.command_catalog,
            limit=limit,
            available_minutes=available_minutes,
        )


@router.get("/command-techniques/{technique_id}")
def command_technique(
    technique_id: str,
    request: Request,
    attempt_key: str = Query(min_length=16, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$"),
    _principal: Principal = Depends(require_role("viewer")),
) -> dict[str, object]:
    catalog = request.app.state.command_catalog
    with request.app.state.db.session_factory() as session:
        attempt = session.scalar(
            select(CommandAttempt).where(CommandAttempt.idempotency_key == attempt_key)
        )
        state = session.get(CommandPracticeState, technique_id)
        if (
            attempt is None
            or state is None
            or attempt.technique_id != technique_id
            or attempt.completed_at is not None
            or attempt.practice_cycle != state.practice_cycle
            or set(attempt.revealed_help or []) != {1, 2, 3, 4}
        ):
            raise AppError(
                403,
                "technique_help_required",
                "Карточка приёма открывается после записи всех ступеней помощи.",
            )
    return {
        "technique": catalog.technique(technique_id).model_dump(),
    }


@router.put("/command-practice/attempts/{attempt_key}/draft")
def command_draft(
    payload: CommandDraftRequest,
    request: Request,
    attempt_key: str = ATTEMPT_KEY,
    _principal: Principal = Depends(require_role("operator")),
) -> dict[str, object]:
    with request.app.state.db.session_factory() as session:
        attempt = save_command_draft(
            session,
            request.app.state.command_catalog,
            attempt_key=attempt_key,
            technique_id=payload.technique_id,
            answer_shell=payload.shell,
            answer=payload.answer,
            observation_answer=payload.observation_answer,
            timezone=payload.timezone,
        )
        return {"attempt_id": attempt.id, "saved": attempt.completed_at is None}


@router.post("/command-practice/attempts/{attempt_key}/hints/{level}")
def command_hint(
    payload: CommandHintRequest,
    request: Request,
    level: int = Path(ge=1, le=4),
    attempt_key: str = ATTEMPT_KEY,
    _principal: Principal = Depends(require_role("operator")),
) -> dict[str, object]:
    with request.app.state.db.session_factory() as session:
        attempt = reveal_command_hint(
            session,
            request.app.state.command_catalog,
            attempt_key=attempt_key,
            technique_id=payload.technique_id,
            answer_shell=payload.shell,
            timezone=payload.timezone,
            level=level,
        )
        challenge = request.app.state.command_catalog.challenge(payload.technique_id)
        hints = [
            hint.model_dump()
            for hint in challenge.hints
            if hint.level in set(attempt.revealed_help or [])
        ]
        return {
            "attempt_id": attempt.id,
            "revealed_help": attempt.revealed_help,
            "hints": hints,
        }


@router.post(
    "/command-practice/attempts/{attempt_key}/complete",
    response_model=CompletionResult,
)
def command_complete(
    payload: CommandCompleteRequest,
    request: Request,
    attempt_key: str = ATTEMPT_KEY,
    _principal: Principal = Depends(require_role("operator")),
) -> CompletionResult:
    with request.app.state.db.session_factory() as session:
        return complete_command_attempt(
            session,
            request.app.state.command_catalog,
            attempt_key=attempt_key,
            technique_id=payload.technique_id,
            answer_shell=payload.shell,
            answer=payload.answer,
            observation_answer=payload.observation_answer,
            dont_remember=payload.dont_remember,
            timezone=payload.timezone,
        )
