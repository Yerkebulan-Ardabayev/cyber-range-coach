from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models import CommandAttempt, CommandPracticeState
from .recall_grader import RecallContract, RecallReason, grade_observation, grade_recall

RECALL_INTERVAL_DAYS = (1, 3, 7, 14, 30)
PRACTICE_ITEM_MINUTES = 5


class SourceRef(BaseModel):
    source: str
    address: str


class CommandTechnique(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    family: str = Field(min_length=1)
    shell: Literal["bash"]
    purpose: str = Field(min_length=1)
    significant_flags: list[str]
    typical_error: str = Field(min_length=1)
    mnemonic_image: str = Field(min_length=1)
    source_refs: list[SourceRef] = Field(min_length=1)
    version: int = Field(ge=1)


class HintStep(BaseModel):
    level: Literal[1, 2, 3, 4]
    label: str
    text: str


class ObservationContract(BaseModel):
    prompt: str = Field(min_length=1)
    expected_concepts: list[list[str]] = Field(min_length=1)
    sample_answer: str = Field(min_length=1)


class PracticeChallenge(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    technique_id: str
    prompt: str = Field(min_length=1)
    estimated_minutes: int = Field(default=PRACTICE_ITEM_MINUTES, ge=1, le=15)
    hints: list[HintStep] = Field(min_length=4, max_length=4)
    recall: RecallContract
    observation: ObservationContract
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered_hints(self) -> PracticeChallenge:
        if [hint.level for hint in self.hints] != [1, 2, 3, 4]:
            raise ValueError("hints must have levels 1, 2, 3, 4 in order")
        return self


CoverageStatus = Literal[
    "included",
    "merged",
    "reference_only",
    "manual_review",
    "needs_image_review",
    "needs_separate_environment",
    "excluded_secret_or_lab_answer",
]


class SourceDocument(BaseModel):
    name: str
    block_count: int = Field(ge=1)
    embedded_images: int = Field(default=0, ge=0)


class SourceCoverage(BaseModel):
    source: str
    address: str
    status: CoverageStatus
    technique_ids: list[str] = Field(default_factory=list)
    note: str = Field(min_length=1)


class CommandCatalogDocument(BaseModel):
    version: int = Field(ge=1)
    sources: list[SourceDocument] = Field(min_length=1)
    techniques: list[CommandTechnique] = Field(min_length=1)
    challenges: list[PracticeChallenge] = Field(min_length=1)
    coverage: list[SourceCoverage] = Field(min_length=1)


class HintLabel(BaseModel):
    level: Literal[1, 2, 3, 4]
    label: str


class PracticeChallengePrompt(BaseModel):
    id: str
    prompt: str
    estimated_minutes: int
    hints: list[HintLabel]
    observation_prompt: str
    version: int


class CommandPracticeItem(BaseModel):
    technique_id: str
    shell: Literal["bash"]
    challenge: PracticeChallengePrompt
    due_at: datetime | None
    overdue: bool
    retry_in_session: bool
    draft_answer: str
    draft_observation_answer: str


class CommandPracticePlan(BaseModel):
    items: list[CommandPracticeItem]
    due_total: int
    new_total: int
    debt_remaining: int
    session_limit: int


class CompletionResult(BaseModel):
    attempt_id: int
    technique_id: str
    reason: RecallReason
    correct: bool
    independent: bool
    observation_correct: bool
    next_due_at: datetime | None
    interval_days: int | None
    retry_in_session: bool
    duplicate: bool = False


class CommandCatalog:
    def __init__(self, directory: Path):
        self.directory = directory
        self.version = 0
        self.techniques: dict[str, CommandTechnique] = {}
        self.challenges: dict[str, PracticeChallenge] = {}
        self.sources: list[SourceDocument] = []
        self.coverage: list[SourceCoverage] = []
        self.reload()

    def reload(self) -> None:
        paths = sorted(self.directory.glob("*.yaml"))
        if not paths:
            raise ValueError(f"no command catalog YAML found in {self.directory}")
        if len(paths) != 1:
            raise ValueError("command catalog must be stored in one canonical YAML file")
        payload = yaml.safe_load(paths[0].read_text(encoding="utf-8"))
        document = CommandCatalogDocument.model_validate(payload)
        techniques = {item.id: item for item in document.techniques}
        if len(techniques) != len(document.techniques):
            raise ValueError("duplicate command technique id")
        challenges = {item.technique_id: item for item in document.challenges}
        if len(challenges) != len(document.challenges):
            raise ValueError("duplicate practice challenge for technique")
        if set(techniques) != set(challenges):
            raise ValueError("every technique must have exactly one practice challenge")
        for technique_id, challenge in challenges.items():
            if challenge.recall.shell != techniques[technique_id].shell:
                raise ValueError(f"shell mismatch for challenge {challenge.id}")
        source_counts = {item.name: item.block_count for item in document.sources}
        coverage_counts: dict[str, int] = {name: 0 for name in source_counts}
        seen_refs: set[tuple[str, str]] = set()
        for item in document.coverage:
            ref = (item.source, item.address)
            if ref in seen_refs:
                raise ValueError(f"duplicate source coverage reference: {ref}")
            seen_refs.add(ref)
            if item.source not in source_counts:
                raise ValueError(f"coverage points to unknown source: {item.source}")
            coverage_counts[item.source] += 1
            for technique_id in item.technique_ids:
                if technique_id not in techniques:
                    raise ValueError(f"coverage points to unknown technique: {technique_id}")
            if item.status in {"included", "merged"} and not item.technique_ids:
                raise ValueError(f"{item.status} coverage needs a technique id: {ref}")
        if coverage_counts != source_counts:
            raise ValueError(
                f"source coverage is incomplete: expected {source_counts}, got {coverage_counts}"
            )
        self.version = document.version
        self.techniques = techniques
        self.challenges = challenges
        self.sources = document.sources
        self.coverage = document.coverage

    def technique(self, technique_id: str) -> CommandTechnique:
        technique = self.techniques.get(technique_id)
        if technique is None:
            raise AppError(
                404,
                "command_technique_not_found",
                "Приём команды не найден.",
                {"technique_id": technique_id},
            )
        return technique

    def challenge(self, technique_id: str) -> PracticeChallenge:
        self.technique(technique_id)
        return self.challenges[technique_id]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def plan_command_practice(
    session: Session,
    catalog: CommandCatalog,
    *,
    limit: int,
    available_minutes: int,
    now: datetime | None = None,
) -> CommandPracticePlan:
    now = now or datetime.now(UTC)
    capacity = min(limit, max(0, available_minutes // PRACTICE_ITEM_MINUTES))
    states = {
        state.technique_id: state
        for state in session.scalars(select(CommandPracticeState)).all()
    }
    due: list[tuple[datetime, str, CommandPracticeState]] = []
    new_ids: list[str] = []
    for technique_id in catalog.techniques:
        state = states.get(technique_id)
        if state is None:
            new_ids.append(technique_id)
            continue
        due_at = _as_utc(state.next_due_at)
        if state.retry_in_session or (due_at is not None and due_at <= now):
            sort_due = due_at or datetime.min.replace(tzinfo=UTC)
            due.append((sort_due, technique_id, state))
        elif state.last_attempt_at is None:
            new_ids.append(technique_id)
    due.sort(key=lambda item: (item[0], item[1]))
    selected_due = due[:capacity]
    remaining_capacity = capacity - len(selected_due)
    selected_new = new_ids[:remaining_capacity]
    items: list[CommandPracticeItem] = []
    for due_at, technique_id, state in selected_due:
        technique = catalog.technique(technique_id)
        challenge = catalog.challenge(technique_id)
        items.append(
            CommandPracticeItem(
                technique_id=technique_id,
                shell=technique.shell,
                challenge=PracticeChallengePrompt(
                    id=challenge.id,
                    prompt=challenge.prompt,
                    estimated_minutes=challenge.estimated_minutes,
                    hints=[HintLabel(level=hint.level, label=hint.label) for hint in challenge.hints],
                    observation_prompt=challenge.observation.prompt,
                    version=challenge.version,
                ),
                due_at=due_at,
                overdue=True,
                retry_in_session=state.retry_in_session,
                draft_answer=state.draft_answer,
                draft_observation_answer=state.draft_observation_answer,
            )
        )
    for technique_id in selected_new:
        state = states.get(technique_id)
        technique = catalog.technique(technique_id)
        challenge = catalog.challenge(technique_id)
        items.append(
            CommandPracticeItem(
                technique_id=technique_id,
                shell=technique.shell,
                challenge=PracticeChallengePrompt(
                    id=challenge.id,
                    prompt=challenge.prompt,
                    estimated_minutes=challenge.estimated_minutes,
                    hints=[HintLabel(level=hint.level, label=hint.label) for hint in challenge.hints],
                    observation_prompt=challenge.observation.prompt,
                    version=challenge.version,
                ),
                due_at=None,
                overdue=False,
                retry_in_session=False,
                draft_answer=state.draft_answer if state else "",
                draft_observation_answer=state.draft_observation_answer if state else "",
            )
        )
    return CommandPracticePlan(
        items=items,
        due_total=len(due),
        new_total=len(new_ids),
        debt_remaining=max(0, len(due) - len(selected_due)),
        session_limit=capacity,
    )


def _state_for(
    session: Session,
    catalog: CommandCatalog,
    technique_id: str,
    timezone: str,
) -> CommandPracticeState:
    challenge = catalog.challenge(technique_id)
    state = session.get(CommandPracticeState, technique_id)
    if state is None:
        state = CommandPracticeState(
            technique_id=technique_id,
            challenge_version=challenge.version,
            data_version=catalog.version,
            timezone=timezone,
            practice_cycle=0,
            current_help_levels=[],
            interval_index=0,
            retry_in_session=False,
            draft_answer="",
            draft_observation_answer="",
        )
        session.add(state)
    else:
        state.timezone = timezone
        state.challenge_version = challenge.version
        state.data_version = catalog.version
    return state


def _attempt_for(
    session: Session,
    catalog: CommandCatalog,
    attempt_key: str,
    technique_id: str,
    answer_shell: str,
    state: CommandPracticeState,
) -> CommandAttempt:
    attempt = session.scalar(
        select(CommandAttempt).where(CommandAttempt.idempotency_key == attempt_key)
    )
    challenge = catalog.challenge(technique_id)
    if attempt is None:
        attempt = CommandAttempt(
            idempotency_key=attempt_key,
            technique_id=technique_id,
            challenge_version=challenge.version,
            data_version=catalog.version,
            practice_cycle=state.practice_cycle,
            answer="",
            observation_answer="",
            revealed_help=[],
            result="draft",
            evidence_kind="recall",
            observation_correct=False,
            dont_remember=False,
        )
        attempt.shell = answer_shell
        session.add(attempt)
    elif attempt.technique_id != technique_id:
        raise AppError(
            409,
            "attempt_technique_mismatch",
            "Ключ попытки уже связан с другим приёмом.",
        )
    elif attempt.completed_at is None and attempt.practice_cycle != state.practice_cycle:
        raise AppError(
            409,
            "attempt_cycle_stale",
            "Попытка относится к уже закрытому циклу повторения.",
        )
    return attempt


def save_command_draft(
    session: Session,
    catalog: CommandCatalog,
    *,
    attempt_key: str,
    technique_id: str,
    answer_shell: str,
    answer: str,
    observation_answer: str,
    timezone: str,
    now: datetime | None = None,
) -> CommandAttempt:
    now = now or datetime.now(UTC)
    state = _state_for(session, catalog, technique_id, timezone)
    attempt = _attempt_for(session, catalog, attempt_key, technique_id, answer_shell, state)
    if attempt.completed_at is not None:
        return attempt
    attempt.answer = answer
    attempt.observation_answer = observation_answer
    state.draft_answer = answer
    state.draft_observation_answer = observation_answer
    state.draft_updated_at = now
    session.commit()
    session.refresh(attempt)
    return attempt


def reveal_command_hint(
    session: Session,
    catalog: CommandCatalog,
    *,
    attempt_key: str,
    technique_id: str,
    answer_shell: str,
    timezone: str,
    level: int,
) -> CommandAttempt:
    state = _state_for(session, catalog, technique_id, timezone)
    attempt = _attempt_for(session, catalog, attempt_key, technique_id, answer_shell, state)
    if attempt.completed_at is not None:
        raise AppError(409, "attempt_completed", "Завершённую попытку нельзя менять.")
    revealed = list(attempt.revealed_help or [])
    expected = len(revealed) + 1
    if level > expected:
        raise AppError(
            409,
            "hint_order_invalid",
            "Подсказки открываются по порядку.",
            {"next_level": expected},
        )
    if level not in revealed:
        revealed.append(level)
        attempt.revealed_help = revealed
    state.current_help_levels = sorted(
        set(state.current_help_levels or []).union(attempt.revealed_help or [])
    )
    session.commit()
    session.refresh(attempt)
    return attempt


def _completion_from_attempt(
    attempt: CommandAttempt,
    state: CommandPracticeState,
    *,
    duplicate: bool,
) -> CompletionResult:
    return CompletionResult(
        attempt_id=attempt.id,
        technique_id=attempt.technique_id,
        reason=RecallReason(attempt.result),
        correct=attempt.result in {
            RecallReason.correct.value,
            RecallReason.correct_with_help.value,
        },
        independent=attempt.result == RecallReason.correct.value,
        observation_correct=attempt.observation_correct,
        next_due_at=_as_utc(attempt.next_due_at),
        interval_days=attempt.interval_days,
        retry_in_session=state.retry_in_session,
        duplicate=duplicate,
    )


def complete_command_attempt(
    session: Session,
    catalog: CommandCatalog,
    *,
    attempt_key: str,
    technique_id: str,
    answer_shell: str,
    answer: str,
    observation_answer: str,
    dont_remember: bool,
    timezone: str,
    now: datetime | None = None,
) -> CompletionResult:
    now = now or datetime.now(UTC)
    state = _state_for(session, catalog, technique_id, timezone)
    attempt = _attempt_for(session, catalog, attempt_key, technique_id, answer_shell, state)
    if attempt.completed_at is not None:
        return _completion_from_attempt(attempt, state, duplicate=True)
    challenge = catalog.challenge(technique_id)
    grade = grade_recall(
        answer,
        answer_shell,
        challenge.recall,
        sorted(set(attempt.revealed_help or []).union(state.current_help_levels or [])),
        dont_remember=dont_remember,
    )
    observation_correct = grade_observation(
        observation_answer,
        challenge.observation.expected_concepts,
    )
    attempt.shell = answer_shell
    attempt.answer = answer
    attempt.observation_answer = observation_answer
    attempt.dont_remember = dont_remember
    attempt.result = grade.reason.value
    attempt.error_kind = None if grade.correct else grade.reason.value
    attempt.observation_correct = observation_correct
    attempt.completed_at = now
    state.last_attempt_at = now
    state.draft_answer = ""
    state.draft_observation_answer = ""
    state.draft_updated_at = now
    interval_days: int | None = None
    if grade.independent:
        interval_days = RECALL_INTERVAL_DAYS[
            min(state.interval_index, len(RECALL_INTERVAL_DAYS) - 1)
        ]
        state.interval_index = min(state.interval_index + 1, len(RECALL_INTERVAL_DAYS))
        state.next_due_at = now + timedelta(days=interval_days)
        state.retry_in_session = False
        state.recalled_without_help_at = now
    elif grade.correct:
        state.recalled_with_help_at = now
        state.next_due_at = now + timedelta(days=1)
        state.retry_in_session = False
    else:
        state.next_due_at = now + timedelta(days=1)
        state.retry_in_session = True
    if observation_correct:
        state.output_interpreted_at = now
    if grade.correct:
        state.practice_cycle += 1
        state.current_help_levels = []
    attempt.next_due_at = state.next_due_at
    attempt.interval_days = interval_days
    session.commit()
    session.refresh(attempt)
    return CompletionResult(
        attempt_id=attempt.id,
        technique_id=technique_id,
        reason=grade.reason,
        correct=grade.correct,
        independent=grade.independent,
        observation_correct=observation_correct,
        next_due_at=_as_utc(state.next_due_at),
        interval_days=interval_days,
        retry_in_session=state.retry_in_session,
    )
