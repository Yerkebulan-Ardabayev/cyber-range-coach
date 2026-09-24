from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request

from ..errors import AppError
from ..schemas import MissionCompleteRequest, MissionDraftRequest
from ..security import Principal, require_role
from ..services.missions import (
    MissionCompletionResult,
    MissionPlan,
    complete_mission_run,
    mission_seed_archive,
    plan_missions,
    save_mission_draft,
)
from ..services.ssh import seed_student_missions

router = APIRouter(prefix="/api/v2", tags=["missions"])

ATTEMPT_KEY = Path(min_length=16, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")


@router.get("/missions/plan", response_model=MissionPlan)
def mission_plan(
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> MissionPlan:
    with request.app.state.db.session_factory() as session:
        return plan_missions(session, request.app.state.mission_catalog)


@router.put("/missions/attempts/{attempt_key}/draft")
def mission_draft(
    payload: MissionDraftRequest,
    request: Request,
    attempt_key: str = ATTEMPT_KEY,
    _principal: Principal = Depends(require_role("operator")),
) -> dict[str, object]:
    with request.app.state.db.session_factory() as session:
        run = save_mission_draft(
            session,
            request.app.state.mission_catalog,
            attempt_key=attempt_key,
            mission_id=payload.mission_id,
            variant_id=payload.variant_id,
            artifact=payload.artifact,
            explanation=payload.explanation,
            structured_facts=payload.structured_facts,
        )
        return {"run_id": run.id, "saved": run.completed_at is None}


@router.post(
    "/missions/attempts/{attempt_key}/complete",
    response_model=MissionCompletionResult,
)
def mission_complete(
    payload: MissionCompleteRequest,
    request: Request,
    attempt_key: str = ATTEMPT_KEY,
    _principal: Principal = Depends(require_role("operator")),
) -> MissionCompletionResult:
    with request.app.state.db.session_factory() as session:
        return complete_mission_run(
            session,
            request.app.state.mission_catalog,
            attempt_key=attempt_key,
            mission_id=payload.mission_id,
            variant_id=payload.variant_id,
            artifact=payload.artifact,
            explanation=payload.explanation,
            structured_facts=payload.structured_facts,
        )


@router.post("/missions/{mission_id}/variants/{variant_id}/seed")
async def mission_seed(
    request: Request,
    mission_id: str = Path(pattern=r"^[a-z0-9][a-z0-9-]+$"),
    variant_id: str = Path(pattern=r"^[a-z0-9][a-z0-9-]+$"),
    _principal: Principal = Depends(require_role("operator")),
) -> dict[str, object]:
    mission = request.app.state.mission_catalog.missions.get(mission_id)
    variant = next((item for item in mission.variants if item.id == variant_id), None) if mission else None
    if mission is None or variant is None:
        raise AppError(404, "mission_not_found", "Миссия или вариант не найдены.")
    archive = mission_seed_archive(mission, variant)
    await seed_student_missions(request.app.state.range_runner, variant.id, archive)
    files = sum(1 for entry in variant.prepared_data if entry.kind != "directory")
    return {"directory": f"~/missions/{variant.id}", "files": files}
