from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..errors import AppError
from ..models import (
    Evidence,
    LabRun,
    LearningSession,
    LinuxHost,
    Note,
    ReviewItem,
    RunStatus,
    SessionStatus,
    TargetProfile,
)
from ..schemas import (
    CorrectionRequest,
    EvidenceResponse,
    ExplanationRequest,
    GradeResponse,
    LabReset,
    LabRunCreate,
    LabRunResponse,
    NoteCreate,
    NoteResponse,
    ReviewResponse,
    SessionCreate,
    SessionPlanRequest,
    SessionPlanResponse,
    SessionResponse,
    TutorFeedbackRequest,
    TutorFeedbackResponse,
)
from ..security import Principal, require_role
from ..services.curriculum import Lesson, step_cleanly_passed
from ..services.grader import grade_run, record_evidence
from ..services.network import verify_target
from ..services.preflight import missing_learning_tools
from ..services.wsl import relay_source_ip_for_start
from .targets import _connect_host

router = APIRouter(prefix="/api/v2", tags=["learning"])


def _lesson_variables(
    run: LabRun, target: TargetProfile | None, request: Request
) -> dict[str, str]:
    variables: dict[str, str] = {}
    if target and run.relay_port:
        connect_host = _connect_host(request)
        path = str(target.health_check.get("path") or "/")
        scheme = urlparse(target.host_endpoint).scheme or "http"
        variables = {
            "target_host": connect_host,
            "target_port": str(run.relay_port),
            "target_url": f"{scheme}://{connect_host}:{run.relay_port}{path}",
            "target_path": path,
        }
    return variables


HELP_WINDOW = timedelta(days=1)


@router.get("/curriculum")
def curriculum(
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> dict[str, object]:
    store = request.app.state.curriculum
    return {
        "tracks": [track.model_dump() for track in store.tracks.values()],
        "lessons": [lesson.public_dump() for lesson in store.ordered_lessons()],
    }


@router.get("/lessons/{lesson_id}")
def lesson(
    lesson_id: str,
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> dict[str, object]:
    lesson_item: Lesson = request.app.state.curriculum.lesson(lesson_id)
    return lesson_item.public_dump()


@router.post("/session-plans", response_model=SessionPlanResponse)
def session_plan(
    payload: SessionPlanRequest,
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> SessionPlanResponse:
    with request.app.state.db.session_factory() as session:
        return cast(
            SessionPlanResponse,
            request.app.state.curriculum.plan(session, payload.duration_minutes),
        )


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session(
    payload: SessionCreate,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> SessionResponse:
    with request.app.state.db.session_factory() as session:
        if payload.lesson_ids:
            lesson_ids = []
            for lesson_id in payload.lesson_ids:
                request.app.state.curriculum.lesson(lesson_id)
                if lesson_id not in lesson_ids:
                    lesson_ids.append(lesson_id)
        else:
            plan = request.app.state.curriculum.plan(session, payload.duration_minutes)
            lesson_ids = [lesson.id for lesson in plan.lessons]
        item = LearningSession(
            duration_minutes=payload.duration_minutes,
            lesson_ids=lesson_ids,
            status=SessionStatus.planned.value,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return SessionResponse.model_validate(item)


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> list[SessionResponse]:
    with request.app.state.db.session_factory() as session:
        items = session.scalars(
            select(LearningSession).order_by(LearningSession.created_at.desc()).limit(30)
        ).all()
        return [SessionResponse.model_validate(item) for item in items]


async def _new_run_unlocked(
    payload: LabRunCreate,
    request: Request,
) -> LabRun:
    lesson = request.app.state.curriculum.lesson(payload.lesson_id)
    with request.app.state.db.session_factory() as session:
        learning_session = session.get(LearningSession, payload.session_id)
        if learning_session is None:
            raise AppError(404, "session_not_found", "Учебная сессия не найдена.")
        previous = request.app.state.curriculum.previous_step(lesson)
        if previous is not None and not step_cleanly_passed(session, previous.id):
            raise AppError(
                409,
                "ladder_step_locked",
                f"Сначала пройдите без подсказки предыдущую ступень: {previous.title}.",
                {"previous_lesson_id": previous.id},
            )
        if payload.lesson_id not in learning_session.lesson_ids:
            raise AppError(
                409,
                "lesson_not_in_session",
                "Урок не входит в выбранный session plan.",
            )
        active = session.scalar(select(LabRun).where(LabRun.status == RunStatus.active.value))
        if active:
            raise AppError(
                409,
                "active_run_exists",
                "Уже есть активный lab run. Его можно открыть, остановить или безопасно сбросить.",
                {"run_id": active.id},
            )
        linux_host = session.scalars(select(LinuxHost).order_by(LinuxHost.id)).first()
        if linux_host is None or not linux_host.confirmed_at:
            raise AppError(
                409, "linux_vm_not_ready", "Linux VM и SSH fingerprint ещё не подтверждены."
            )
        target: TargetProfile | None = None
        if lesson.requires_target:
            if payload.target_id is None:
                raise AppError(422, "target_required", "Для этого урока нужна подтверждённая цель.")
            target = session.get(TargetProfile, payload.target_id)
            if target is None:
                raise AppError(404, "target_not_found", "Учебная цель не найдена.")
            if lesson.target_tags and not set(lesson.target_tags).intersection(
                target.allowed_curriculum_tags
            ):
                raise AppError(
                    409,
                    "target_not_approved_for_lesson",
                    "Цель не подтверждена для тегов этого урока.",
                )
            session.expunge(target)
        session.expunge(linux_host)
    relay_port: int | None = None
    target_fingerprint: str | None = None
    student_boundary = await request.app.state.terminals.verify_student_boundary()
    if student_boundary.get("safe") is not True:
        raise AppError(
            409,
            "student_boundary_failed",
            "Lab не запускается: student получил sudo или доступ к Docker socket.",
            student_boundary,
        )
    runner_evidence = await request.app.state.range_runner.tools()
    missing_tools = missing_learning_tools(runner_evidence, request.app.state.range_runner.protocol)
    if missing_tools:
        raise AppError(
            409,
            "linux_tools_missing",
            "Lab не запускается: в Linux VM отсутствуют обязательные инструменты курса.",
            {"missing_tools": missing_tools},
        )
    if target:
        verified = await verify_target(target)
        if not verified.reachable:
            raise AppError(
                409,
                "target_not_reachable",
                "Windows не получила проверяемый ответ от выбранной Docker-цели.",
                verified.model_dump(mode="json"),
            )
        parsed = urlparse(target.host_endpoint)
        upstream_host = parsed.hostname or "127.0.0.1"
        upstream_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        relay_source_ip = await relay_source_ip_for_start(
            request.app.state.db,
            request.app.state.runner,
            request.app.state.settings.subprocess_timeout_seconds,
            linux_host,
        )
        handle = await request.app.state.relays.start(
            target.id,
            upstream_host,
            upstream_port,
            relay_source_ip,
            bind_host=_connect_host(request),
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
        relay_port = handle.port
        target_fingerprint = target.fingerprint
    with request.app.state.db.session_factory() as session:
        learning_session = session.get(LearningSession, payload.session_id)
        if learning_session is None:
            if target:
                await request.app.state.relays.stop(target.id)
            raise AppError(404, "session_not_found", "Учебная сессия исчезла.")
        run = LabRun(
            session_id=payload.session_id,
            lesson_id=payload.lesson_id,
            skill_id=lesson.skill_id,
            target_id=payload.target_id,
            target_fingerprint=target_fingerprint,
            prediction=payload.prediction,
            relay_port=relay_port,
        )
        learning_session.status = SessionStatus.active.value
        learning_session.started_at = learning_session.started_at or datetime.now(UTC)
        learning_session.current_lesson_id = payload.lesson_id
        session.add(run)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if target:
                await request.app.state.relays.stop(target.id)
            raise AppError(
                409,
                "active_run_exists",
                "Уже есть активный lab run. Откройте или остановите его.",
            ) from exc
        session.refresh(run)
        return run


async def _new_run(payload: LabRunCreate, request: Request) -> LabRun:
    async with request.app.state.run_start_lock:
        return await _new_run_unlocked(payload, request)


@router.post("/lab-runs", response_model=LabRunResponse, status_code=201)
async def create_lab_run(
    payload: LabRunCreate,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> LabRunResponse:
    return LabRunResponse.model_validate(await _new_run(payload, request))


@router.get("/lab-runs", response_model=list[LabRunResponse])
def list_lab_runs(
    request: Request,
    status: str | None = None,
    _principal: Principal = Depends(require_role("viewer")),
) -> list[LabRunResponse]:
    with request.app.state.db.session_factory() as session:
        statement = select(LabRun).order_by(LabRun.created_at.desc()).limit(50)
        if status:
            statement = statement.where(LabRun.status == status)
        runs = session.scalars(statement).all()
        return [LabRunResponse.model_validate(run) for run in runs]


@router.get("/lab-runs/{run_id}", response_model=LabRunResponse)
def get_lab_run(
    run_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> LabRunResponse:
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        if run is None:
            raise AppError(404, "run_not_found", "Lab run не найден.")
        return LabRunResponse.model_validate(run)


@router.get("/lab-runs/{run_id}/lesson")
def get_run_lesson(
    run_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> dict[str, object]:
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        if run is None:
            raise AppError(404, "run_not_found", "Lab run не найден.")
        lesson_item = request.app.state.curriculum.lesson(run.lesson_id)
        target = session.get(TargetProfile, run.target_id) if run.target_id else None
        help_used = run.help_used
    variables = _lesson_variables(run, target, request)
    public = lesson_item.public_dump(reveal_command=help_used)
    rendered = str(public["command"])
    for key, value in variables.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return {**public, "rendered_command": rendered, "variables": variables}


@router.post("/lab-runs/{run_id}/reveal-command")
def reveal_command(
    run_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> dict[str, object]:
    """Open the hidden command of a ladder step; this counts as help."""
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        if run is None or run.status != RunStatus.active.value:
            raise AppError(404, "active_run_not_found", "Активный lab run не найден.")
        if request.app.state.curriculum.lesson(run.lesson_id).ladder_step == 3:
            raise AppError(
                409,
                "no_help_on_transfer",
                "На ступени переноса подсказок нет: задачу решают без показа команды.",
            )
        if not run.help_used:
            run.help_used = True
            run.help_opened_at = datetime.now(UTC)
        session.commit()
    return get_run_lesson(run_id, request, _principal)


@router.post("/lab-runs/{run_id}/explanation", response_model=LabRunResponse)
def save_explanation(
    run_id: int,
    payload: ExplanationRequest,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> LabRunResponse:
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        if run is None or run.status != RunStatus.active.value:
            raise AppError(404, "active_run_not_found", "Активный lab run не найден.")
        if run.grader_status != "passed":
            raise AppError(
                409,
                "observation_not_passed",
                "Сначала подтвердите наблюдение deterministic grader.",
            )
        run.explanation = payload.text
        run.tutor_feedback_at = None
        run.tutor_question = None
        run.tutor_explanation = None
        run.correction = None
        session.commit()
        session.refresh(run)
        return LabRunResponse.model_validate(run)


@router.post("/explanations", response_model=LabRunResponse)
def save_explanation_alias(
    run_id: int,
    payload: ExplanationRequest,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> LabRunResponse:
    return save_explanation(run_id, payload, request, _principal)


@router.post("/lab-runs/{run_id}/grade", response_model=GradeResponse)
async def grade(
    run_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> GradeResponse:
    await request.app.state.terminals.flush(run_id)
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        if run is None or run.status != RunStatus.active.value:
            raise AppError(404, "active_run_not_found", "Активный lab run не найден.")
        lesson_item = request.app.state.curriculum.lesson(run.lesson_id)
        target = session.get(TargetProfile, run.target_id) if run.target_id else None
        variables = _lesson_variables(run, target, request)
        observation: str | None = None
        if lesson_item.grader.source == "probe":
            if not run.relay_port or not lesson_item.grader.probe:
                raise AppError(409, "probe_not_configured", "Для урока нет structured probe.")
            if lesson_item.grader.probe == "relay":
                probe = await request.app.state.range_runner.relay(run.relay_port)
            elif lesson_item.grader.probe == "nmap":
                probe = await request.app.state.range_runner.nmap(run.relay_port)
            else:
                if target is None:
                    raise AppError(409, "target_not_found", "Target profile исчез.")
                parsed = urlparse(target.host_endpoint)
                probe = await request.app.state.range_runner.http(
                    run.relay_port,
                    parsed.scheme or "http",
                    str(target.health_check.get("path") or "/"),
                )
            observation = json.dumps(probe, sort_keys=True)
        return grade_run(session, run, lesson_item, variables, observation)


@router.post("/tutor-feedback", response_model=TutorFeedbackResponse)
async def tutor_feedback(
    payload: TutorFeedbackRequest,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> TutorFeedbackResponse:
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, payload.run_id)
        if run is None or run.status != RunStatus.active.value:
            raise AppError(404, "active_run_not_found", "Активный lab run не найден.")
        if run.grader_status != "passed" or not run.explanation:
            raise AppError(
                409,
                "explanation_not_ready",
                "Сначала пройдите observation gate и сохраните своё объяснение.",
            )
        lesson_item = request.app.state.curriculum.lesson(run.lesson_id)
        explanation = run.explanation
        facts = [
            str(check.get("pattern"))
            for check in (run.grader_report or {}).get("checks", [])
            if isinstance(check, dict) and check.get("passed") is True
        ]
    context = (
        f"Урок: {lesson_item.title}\n"
        f"Термин: {lesson_item.term.name}: {lesson_item.term.definition}\n"
        f"Факты: {facts}\n"
        f"Объяснение ученика: {explanation}\n"
        f"Детерминированный вопрос: {lesson_item.explanation_prompt}"
    )
    feedback = cast(
        TutorFeedbackResponse,
        await request.app.state.ai.tutor_feedback(context, lesson_item.explanation_prompt),
    )
    with request.app.state.db.session_factory() as session:
        stored = session.get(LabRun, payload.run_id)
        if stored is None or stored.status != RunStatus.active.value:
            raise AppError(409, "run_changed", "Lab run изменился во время tutor feedback.")
        stored.tutor_feedback_at = datetime.now(UTC)
        stored.tutor_question = feedback.question
        stored.tutor_explanation = feedback.explanation
        session.commit()
    return feedback


@router.post("/lab-runs/{run_id}/finalize", response_model=GradeResponse)
async def finalize_run(
    run_id: int,
    payload: CorrectionRequest,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> GradeResponse:
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        if run is None or run.status != RunStatus.active.value:
            raise AppError(404, "active_run_not_found", "Активный lab run не найден.")
        if run.grader_status != "passed" or not run.explanation or not run.tutor_feedback_at:
            raise AppError(
                409,
                "learning_cycle_incomplete",
                "Нужны passed observation, объяснение и вопрос наставника.",
            )
        if (
            " ".join(payload.corrected_conclusion.split()).casefold()
            == " ".join(run.explanation.split()).casefold()
        ):
            raise AppError(
                409,
                "correction_unchanged",
                "Исправленный вывод должен отличаться от первого объяснения.",
            )
        target_id = run.target_id
    await request.app.state.terminals.stop(run_id)
    if target_id:
        await request.app.state.relays.stop(target_id)
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        if run is None:
            raise AppError(404, "run_not_found", "Lab run исчез.")
        lesson_item = request.app.state.curriculum.lesson(run.lesson_id)
        run.correction = (
            f"Исправленный вывод: {payload.corrected_conclusion}\n"
            f"Ограничение: {payload.limitation}\n"
            f"Следующая проверка: {payload.next_test}"
        )
        # Opened help counts for a full day in any learning session, so the
        # command seen a minute ago can not be re-typed for a clean credit;
        # the clean attempt belongs to tomorrow's review (spec 11.3 Д).
        last_clean_credit = session.scalar(
            select(func.max(Evidence.created_at))
            .join(LabRun, LabRun.id == Evidence.run_id)
            .where(LabRun.lesson_id == run.lesson_id, Evidence.grader_decision == "passed")
        )
        help_query = select(LabRun.id).where(
            LabRun.lesson_id == run.lesson_id,
            LabRun.help_used.is_(True),
            LabRun.help_opened_at > datetime.now(UTC) - HELP_WINDOW,
        )
        if last_clean_credit is not None:
            help_query = help_query.where(LabRun.help_opened_at > last_clean_credit)
        # Help opened in this very run always counts, however old the run is.
        help_used = run.help_used or session.scalar(help_query.limit(1))
        stage = record_evidence(
            session,
            run,
            lesson_item,
            ladder=request.app.state.curriculum.has_ladder(lesson_item.skill_id),
            help_used=bool(help_used),
        )
        run.status = RunStatus.completed.value
        run.stopped_at = datetime.now(UTC)
        learning_session = session.get(LearningSession, run.session_id)
        if learning_session is not None:
            completed_lessons = set(
                session.scalars(
                    select(LabRun.lesson_id).where(
                        LabRun.session_id == learning_session.id,
                        LabRun.status == RunStatus.completed.value,
                    )
                ).all()
            )
            if set(learning_session.lesson_ids).issubset(completed_lessons):
                learning_session.status = SessionStatus.completed.value
                learning_session.completed_at = datetime.now(UTC)
                learning_session.current_lesson_id = None
        session.commit()
        return GradeResponse(
            run_id=run.id,
            status="passed",
            checks=list((run.grader_report or {}).get("checks", [])),
            explanation_prompt=lesson_item.explanation_prompt,
            evidence_stage=stage,
        )


async def _stop_run(run_id: int, request: Request, status: str) -> LabRun:
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        if run is None:
            raise AppError(404, "run_not_found", "Lab run не найден.")
        target_id = run.target_id
    await request.app.state.terminals.stop(run_id)
    if target_id:
        await request.app.state.relays.stop(target_id)
    with request.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        if run is None:
            raise AppError(404, "run_not_found", "Lab run не найден.")
        run.status = status
        run.stopped_at = datetime.now(UTC)
        session.commit()
        session.refresh(run)
        return cast(LabRun, run)


@router.post("/lab-runs/{run_id}/stop", response_model=LabRunResponse)
async def stop_run(
    run_id: int,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> LabRunResponse:
    return LabRunResponse.model_validate(await _stop_run(run_id, request, RunStatus.stopped.value))


@router.post("/lab-runs/{run_id}/reset", response_model=LabRunResponse)
async def reset_run(
    run_id: int,
    payload: LabReset,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> LabRunResponse:
    old = await _stop_run(run_id, request, RunStatus.abandoned.value)
    replacement = await _new_run(
        LabRunCreate(
            session_id=old.session_id,
            lesson_id=old.lesson_id,
            target_id=old.target_id,
            prediction=payload.prediction,
        ),
        request,
    )
    return LabRunResponse.model_validate(replacement)


@router.get("/evidence", response_model=list[EvidenceResponse])
def evidence(
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> list[EvidenceResponse]:
    with request.app.state.db.session_factory() as session:
        items = session.scalars(select(Evidence).order_by(Evidence.created_at.desc())).all()
        return [EvidenceResponse.model_validate(item) for item in items]


@router.get("/reviews", response_model=list[ReviewResponse])
def reviews(
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> list[ReviewResponse]:
    with request.app.state.db.session_factory() as session:
        items = session.scalars(select(ReviewItem).order_by(ReviewItem.due_at)).all()
        return [ReviewResponse.model_validate(item) for item in items]


@router.get("/notes", response_model=list[NoteResponse])
def notes(
    request: Request,
    _principal: Principal = Depends(require_role("viewer")),
) -> list[NoteResponse]:
    with request.app.state.db.session_factory() as session:
        items = session.scalars(select(Note).order_by(Note.updated_at.desc())).all()
        return [NoteResponse.model_validate(item) for item in items]


@router.post("/notes", response_model=NoteResponse, status_code=201)
def create_note(
    payload: NoteCreate,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> NoteResponse:
    with request.app.state.db.session_factory() as session:
        note = Note(**payload.model_dump())
        session.add(note)
        session.commit()
        session.refresh(note)
        return NoteResponse.model_validate(note)


@router.put("/notes/{note_id}", response_model=NoteResponse)
def update_note(
    note_id: int,
    payload: NoteCreate,
    request: Request,
    _principal: Principal = Depends(require_role("operator")),
) -> NoteResponse:
    with request.app.state.db.session_factory() as session:
        note = session.get(Note, note_id)
        if note is None:
            raise AppError(404, "note_not_found", "Заметка не найдена.")
        for key, value in payload.model_dump().items():
            setattr(note, key, value)
        note.updated_at = datetime.now(UTC)
        session.commit()
        session.refresh(note)
        return NoteResponse.model_validate(note)
