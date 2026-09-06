from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Evidence, LabRun, ReviewItem, SkillStage, SkillState
from ..schemas import GradeResponse
from .curriculum import Lesson

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
STAGE_ORDER = {
    SkillStage.introduced.value: 0,
    SkillStage.guided.value: 1,
    SkillStage.independent.value: 2,
    SkillStage.transfer.value: 3,
}


def clean_terminal(text: str) -> str:
    return ANSI_ESCAPE.sub("", text).replace("\r", "")


def terminal_observation(
    transcript: str,
    submitted_commands: list[str],
    approved_command_index: int,
    command_offsets: list[int] | None = None,
    allowed_response_count: int = 0,
) -> str:
    """Return the candidate observation after the approved command echo.

    The caller separately requires the approved command to be the first shell
    submission of a clean lab run. Offsets then exclude shell startup output and
    bound any later submission.
    """
    if approved_command_index >= len(submitted_commands):
        return ""
    needle = clean_terminal(submitted_commands[approved_command_index])
    if not needle:
        return ""
    offsets = list(command_offsets or [])
    if len(offsets) == len(submitted_commands) and all(
        0 <= offset <= len(transcript) for offset in offsets
    ) and offsets == sorted(offsets):
        segment_start = offsets[approved_command_index]
        next_input_index = approved_command_index + allowed_response_count + 1
        segment_end = offsets[next_input_index] if next_input_index < len(offsets) else len(transcript)
        segment = clean_terminal(transcript[segment_start:segment_end])
        echo = segment.find(needle)
    else:
        # Imported/test transcripts without gateway offsets use a conservative
        # fallback anchored to the final echo of the approved command.
        segment = clean_terminal(transcript)
        echo = segment.rfind(needle)
    if echo < 0:
        return ""
    return segment[echo + len(needle) :]


def _expand_pattern(pattern: str, variables: dict[str, str]) -> str:
    expanded = pattern
    for key, value in variables.items():
        expanded = expanded.replace("{{" + key + "}}", re.escape(value))
    return expanded


def _render_command(command: str, variables: dict[str, str]) -> str:
    rendered = command
    for key, value in variables.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _same_command(actual: str, expected: str) -> bool:
    return " ".join(actual.split()) == " ".join(expected.split())


def grade_run(
    session: Session,
    run: LabRun,
    lesson: Lesson,
    variables: dict[str, str] | None = None,
    observation: str | None = None,
) -> GradeResponse:
    variables = variables or {}
    rendered_command = _render_command(lesson.command, variables)
    submitted_commands = list(run.terminal_inputs or [])
    matching_command_indexes = [
        index
        for index, actual in enumerate(submitted_commands)
        if _same_command(actual, rendered_command)
    ]
    command_seen = bool(matching_command_indexes)
    clean_attempt_boundary = command_seen and matching_command_indexes[-1] == 0
    response_count_ok = True
    if command_seen:
        responses = submitted_commands[matching_command_indexes[-1] + 1 :]
        response_count_ok = len(responses) == lesson.grader.response_count and all(
            response.strip() for response in responses
        )
    if lesson.grader.source == "probe":
        source = observation or ""
    elif lesson.grader.source == "transcript":
        source = terminal_observation(
            run.transcript,
            submitted_commands,
            matching_command_indexes[-1] if matching_command_indexes else 0,
            list(run.terminal_input_offsets or []),
            lesson.grader.response_count,
        )
    else:
        source = run.explanation or ""
    normalized = clean_terminal(source)
    checks: list[dict[str, object]] = []
    command_required = lesson.grader.source in {"transcript", "probe"}
    if command_required:
        integrity_ok = run.input_integrity == "verified"
        checks.append(
            {
                "kind": "input_integrity",
                "pattern": "terminal line ledger verified for this run",
                "passed": integrity_ok,
                "reason": run.input_integrity_reason,
            }
        )
        checks.append(
            {
                "kind": "command",
                "pattern": "approved lesson command submitted",
                "passed": command_seen,
            }
        )
        checks.append(
            {
                "kind": "attempt_boundary",
                "pattern": "approved command is the first shell submission in this run",
                "passed": clean_attempt_boundary,
            }
        )
        if lesson.grader.source == "transcript":
            checks.append(
                {
                    "kind": "responses",
                    "pattern": f"exactly {lesson.grader.response_count} interactive responses",
                    "passed": response_count_ok,
                }
            )
    else:
        command_seen = True
    if (
        not normalized.strip()
        or not command_seen
        or not clean_attempt_boundary
        or not response_count_ok
        or (command_required and run.input_integrity != "verified")
    ):
        report = GradeResponse(
            run_id=run.id,
            status="needs_evidence",
            checks=checks,
            explanation_prompt=lesson.explanation_prompt,
        )
        run.grader_status = report.status
        run.grader_report = report.model_dump(mode="json")
        session.commit()
        return report
    passed = True
    for pattern in lesson.grader.required_patterns:
        expanded = _expand_pattern(pattern, variables)
        matched = re.search(expanded, normalized, re.IGNORECASE | re.MULTILINE) is not None
        checks.append({"kind": "required", "pattern": pattern, "passed": matched})
        passed = passed and matched
    for pattern in lesson.grader.forbidden_patterns:
        expanded = _expand_pattern(pattern, variables)
        absent = re.search(expanded, normalized, re.IGNORECASE | re.MULTILINE) is None
        checks.append({"kind": "forbidden", "pattern": pattern, "passed": absent})
        passed = passed and absent
    status = "passed" if passed else "failed"
    report = GradeResponse(
        run_id=run.id,
        status=status,
        checks=checks,
        explanation_prompt=lesson.explanation_prompt,
        evidence_stage=None,
    )
    run.grader_status = status
    run.grader_report = report.model_dump(mode="json")
    session.commit()
    return report


def record_evidence(session: Session, run: LabRun, lesson: Lesson) -> str:
    existing = session.scalar(
        select(Evidence).where(Evidence.run_id == run.id, Evidence.skill_id == lesson.skill_id)
    )
    if existing is not None:
        return existing.stage
    state = session.get(SkillState, lesson.skill_id)
    if state is None:
        state = SkillState(skill_id=lesson.skill_id)
        session.add(state)
    fingerprints = list(state.successful_fingerprints or [])
    if run.target_fingerprint and run.target_fingerprint not in fingerprints:
        fingerprints.append(run.target_fingerprint)
    current_rank = STAGE_ORDER.get(state.stage, 0)
    candidate_rank = min(STAGE_ORDER[SkillStage.independent.value], current_rank + 1)
    candidate = next(stage for stage, rank in STAGE_ORDER.items() if rank == candidate_rank)
    if len(fingerprints) >= 2 and current_rank >= STAGE_ORDER[SkillStage.independent.value]:
        candidate = SkillStage.transfer.value
    if STAGE_ORDER[candidate] > STAGE_ORDER.get(state.stage, 0):
        state.stage = candidate
    state.successful_fingerprints = fingerprints
    state.last_seen_at = datetime.now(UTC)
    interval = {
        SkillStage.introduced.value: 1,
        SkillStage.guided.value: 2,
        SkillStage.independent.value: 7,
        SkillStage.transfer.value: 21,
    }[state.stage]
    state.next_review_at = datetime.now(UTC) + timedelta(days=interval)
    session.add(
        Evidence(
            run_id=run.id,
            skill_id=lesson.skill_id,
            stage=state.stage,
            source_type="structured_probe" if lesson.grader.source == "probe" else "terminal",
            source_id=str(run.id),
            target_fingerprint=run.target_fingerprint,
            fact=lesson.grader.fact_template,
            grader_decision="passed",
        )
    )
    now = datetime.now(UTC)
    due_reviews = session.scalars(
        select(ReviewItem).where(
            ReviewItem.skill_id == lesson.skill_id,
            ReviewItem.completed_at.is_(None),
            ReviewItem.due_at <= now,
        )
    ).all()
    for review in due_reviews:
        review.completed_at = now
    future_review = session.scalar(
        select(ReviewItem).where(
            ReviewItem.skill_id == lesson.skill_id,
            ReviewItem.lesson_id == lesson.id,
            ReviewItem.completed_at.is_(None),
        )
    )
    if future_review is None:
        session.add(
            ReviewItem(
                skill_id=lesson.skill_id,
                lesson_id=lesson.id,
                due_at=state.next_review_at,
                reason=f"Повторить навык и укрепить этап {state.stage}.",
            )
        )
    else:
        future_review.due_at = state.next_review_at
        future_review.reason = f"Повторить навык и укрепить этап {state.stage}."
    return state.stage
