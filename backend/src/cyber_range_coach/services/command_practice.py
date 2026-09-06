from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models import (
    AssessmentWindow,
    CommandAttempt,
    CommandPracticeState,
    HelpEvent,
)
from .recall_grader import (
    RecallContract,
    RecallReason,
    Shell,
    grade_recall,
)

RECALL_INTERVAL_DAYS = (1, 3, 7, 14, 30)
PRACTICE_ITEM_MINUTES = 5

# A rehearsal in the browser is not a run on a stand. Windows techniques stay
# "awaiting_stand" until the learner has an own Windows target to run them on.
ExecutionStatus = Literal["range_ready", "awaiting_stand"]
AttemptType = Literal["assessment", "rehearsal"]
GRADING_POLICY_VERSION = 2
GRADER_VERSION = 2
HELP_COOLDOWN = timedelta(hours=24)


class SourceRef(BaseModel):
    source: str
    address: str


class CommandTechnique(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    family: str = Field(min_length=1)
    shell: Shell
    execution_status: ExecutionStatus = "range_ready"
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


class ChallengeContext(BaseModel):
    shell: Shell
    working_directory: str | None = None
    named_inputs: dict[str, str] = Field(min_length=1)
    constraints: list[str] = Field(min_length=1)


class AnswerField(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    label: str = Field(min_length=1)
    kind: Literal["command"] = "command"


class ObservationField(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    label: str = Field(min_length=1)
    accepted_values: list[str] = Field(min_length=1)
    accepted_patterns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_patterns(self) -> ObservationField:
        for pattern in self.accepted_patterns:
            re.compile(pattern)
        return self


class PublicObservationField(BaseModel):
    id: str
    label: str
    required: bool = True


class ObservationContract(BaseModel):
    prompt: str = Field(min_length=1)
    example_output: str = Field(min_length=1)
    fields: list[ObservationField] = Field(min_length=1)
    sample_answer: str = Field(min_length=1)


class PracticeChallenge(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    technique_id: str
    prompt: str = Field(min_length=1)
    context: ChallengeContext
    answer_fields: list[AnswerField] = Field(min_length=1)
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


# A source block that starts with the name of a shell program is a candidate
# technique. Filing it as prose without a word silently loses material, so such
# a block has to carry a status that states the decision.
COMMAND_LEAD = re.compile(
    r"^(pwd|ls|cd|cat|grep|chmod|find|cut|sort|head|tail|stat|file|ssh|sudo|"
    r"reg|net|schtasks|tasklist|taskkill|dir|copy|findstr|icacls|attrib|type|"
    r"more|set|setx|echo|mklink|fsutil|where|start|del|ren|mkdir|vol|ver|"
    r"runas|powershell|whoami|systeminfo)\b"
)


class SourceCoverage(BaseModel):
    source: str
    address: str
    status: CoverageStatus
    technique_ids: list[str] = Field(default_factory=list)
    note: str = Field(min_length=1)
    # Name of the program the source block starts with, when it starts with a
    # command at all. Stored in the catalog so that the gate also works where
    # the original .docx sources are not around.
    lead: str | None = None

    @model_validator(mode="after")
    def command_block_is_decided(self) -> SourceCoverage:
        if self.lead and self.status == "reference_only":
            raise ValueError(
                f"{self.source} {self.address}: block starts with the command "
                f"{self.lead}, it cannot be filed as prose without a decision"
            )
        return self


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
    context: ChallengeContext
    answer_fields: list[AnswerField]
    estimated_minutes: int
    hints: list[HintLabel]
    observation_prompt: str
    version: int


class CommandPracticeItem(BaseModel):
    technique_id: str
    shell: Shell
    execution_status: ExecutionStatus
    challenge: PracticeChallengePrompt
    due_at: datetime | None
    overdue: bool
    retry_in_session: bool
    draft_answer: str
    draft_observation_answer: str
    draft_attempt_key: str | None = None
    attempt_type: AttemptType
    eligible_at: datetime | None = None
    window_id: int | None = None
    phase: Literal["recall", "observation"] = "recall"


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
    verification_status: Literal["verified", "unverified"] = "verified"
    detail: str
    attempt_type: AttemptType
    completed: bool
    observation_example: str | None = None
    observation_fields: list[PublicObservationField] = Field(default_factory=list)


class ObservationCompletionResult(BaseModel):
    attempt_id: int
    technique_id: str
    observation_correct: bool
    field_errors: dict[str, str] = Field(default_factory=dict)
    free_text_review_status: Literal["not_assessed"] = "not_assessed"
    completed: bool


class ReferenceDisclosure(BaseModel):
    technique: CommandTechnique
    event_id: int
    shown_at: datetime
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
        techniques: dict[str, CommandTechnique] = {}
        challenges: dict[str, PracticeChallenge] = {}
        sources: list[SourceDocument] = []
        coverage: list[SourceCoverage] = []
        versions: set[int] = set()
        for path in paths:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            document = CommandCatalogDocument.model_validate(payload)
            versions.add(document.version)
            self._merge(path.name, document, techniques, challenges, sources, coverage)
        if len(versions) != 1:
            raise ValueError("every command catalog file must declare the same version")
        self.version = versions.pop()
        self.techniques = techniques
        self.challenges = challenges
        self.sources = sources
        self.coverage = coverage

    @staticmethod
    def _merge(
        filename: str,
        document: CommandCatalogDocument,
        techniques: dict[str, CommandTechnique],
        challenges: dict[str, PracticeChallenge],
        sources: list[SourceDocument],
        coverage: list[SourceCoverage],
    ) -> None:
        """Validate one catalog file and fold it into the merged catalog.

        Coverage is validated inside its own file: a Windows coverage entry must
        not close a gap in the Linux source list, and every declared source block
        needs exactly one classification.
        """
        local: dict[str, CommandTechnique] = {}
        for item in document.techniques:
            if item.id in techniques or item.id in local:
                raise ValueError(f"duplicate command technique id: {item.id}")
            local[item.id] = item
        local_challenges: dict[str, PracticeChallenge] = {}
        for entry in document.challenges:
            if entry.technique_id in local_challenges:
                raise ValueError("duplicate practice challenge for technique")
            local_challenges[entry.technique_id] = entry
        if set(local) != set(local_challenges):
            raise ValueError("every technique must have exactly one practice challenge")
        for technique_id, challenge in local_challenges.items():
            if challenge.recall.shell != local[technique_id].shell:
                raise ValueError(f"shell mismatch for challenge {challenge.id}")
        source_counts: dict[str, int] = {}
        for source in document.sources:
            known = any(existing.name == source.name for existing in sources)
            if known or source.name in source_counts:
                raise ValueError(f"duplicate source document: {source.name}")
            source_counts[source.name] = source.block_count
        coverage_counts: dict[str, int] = {name: 0 for name in source_counts}
        seen_refs: set[tuple[str, str]] = set()
        for record in document.coverage:
            ref = (record.source, record.address)
            if ref in seen_refs:
                raise ValueError(f"duplicate source coverage reference: {ref}")
            seen_refs.add(ref)
            if record.source not in source_counts:
                raise ValueError(f"coverage points to unknown source: {record.source}")
            coverage_counts[record.source] += 1
            for technique_id in record.technique_ids:
                if technique_id not in local:
                    raise ValueError(f"coverage points to unknown technique: {technique_id}")
            if record.status in {"included", "merged"} and not record.technique_ids:
                raise ValueError(f"{record.status} coverage needs a technique id: {ref}")
        if coverage_counts != source_counts:
            raise ValueError(
                f"source coverage is incomplete in {filename}: "
                f"expected {source_counts}, got {coverage_counts}"
            )
        techniques.update(local)
        challenges.update(local_challenges)
        sources.extend(document.sources)
        coverage.extend(document.coverage)

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


def _interleave_by_shell(technique_ids: list[str], catalog: CommandCatalog) -> list[str]:
    """Round robin over shells so one catalog cannot bury the other.

    New techniques are taken in catalog order, and the Linux catalog is read
    first. Without interleaving the 96 cmd.exe techniques would sit behind
    every remaining bash one and never reach a session.
    """
    queues: dict[str, list[str]] = {}
    for technique_id in technique_ids:
        queues.setdefault(catalog.techniques[technique_id].shell, []).append(technique_id)
    order = sorted(queues)
    mixed: list[str] = []
    index = 0
    while any(queues[shell] for shell in order):
        for shell in order:
            queue = queues[shell]
            if index < len(queue):
                mixed.append(queue[index])
        index += 1
        if all(index >= len(queues[shell]) for shell in order):
            break
    return mixed


def _public_challenge(challenge: PracticeChallenge) -> PracticeChallengePrompt:
    return PracticeChallengePrompt(
        id=challenge.id,
        prompt=challenge.prompt,
        context=challenge.context,
        answer_fields=challenge.answer_fields,
        estimated_minutes=challenge.estimated_minutes,
        hints=[HintLabel(level=hint.level, label=hint.label) for hint in challenge.hints],
        observation_prompt=challenge.observation.prompt,
        version=challenge.version,
    )


def _assessment_allowed(state: CommandPracticeState | None, now: datetime) -> bool:
    if state is None:
        return True
    due_at = _as_utc(state.next_due_at)
    eligible_at = _as_utc(state.eligible_at)
    return (due_at is None or due_at <= now) and (eligible_at is None or eligible_at <= now)


def _pending_attempt(session: Session, technique_id: str) -> CommandAttempt | None:
    return session.scalar(
        select(CommandAttempt)
        .where(
            CommandAttempt.technique_id == technique_id,
            CommandAttempt.completed_at.is_(None),
        )
        .order_by(CommandAttempt.started_at.desc(), CommandAttempt.id.desc())
    )


def _active_window(session: Session, technique_id: str) -> AssessmentWindow | None:
    return session.scalar(
        select(AssessmentWindow).where(
            AssessmentWindow.technique_id == technique_id,
            AssessmentWindow.window_type == "assessment",
            AssessmentWindow.closed_at.is_(None),
        )
    )


def _practice_item(
    session: Session,
    catalog: CommandCatalog,
    technique_id: str,
    state: CommandPracticeState | None,
    *,
    due_at: datetime | None,
    overdue: bool,
    now: datetime,
) -> CommandPracticeItem:
    technique = catalog.technique(technique_id)
    challenge = catalog.challenge(technique_id)
    pending = _pending_attempt(session, technique_id)
    active_window = _active_window(session, technique_id)
    attempt_type: AttemptType = "assessment" if _assessment_allowed(state, now) else "rehearsal"
    if active_window is not None:
        attempt_type = "assessment"
    phase: Literal["recall", "observation"] = "recall"
    if pending is not None and pending.recall_completed_at is not None:
        phase = "observation"
        attempt_type = pending.attempt_type  # type: ignore[assignment]
    return CommandPracticeItem(
        technique_id=technique_id,
        shell=technique.shell,
        execution_status=technique.execution_status,
        challenge=_public_challenge(challenge),
        due_at=due_at,
        overdue=overdue,
        retry_in_session=bool(state and state.retry_in_session),
        draft_answer=pending.answer
        if pending is not None
        else (state.draft_answer if state else ""),
        draft_observation_answer=(
            pending.observation_answer
            if pending is not None
            else (state.draft_observation_answer if state else "")
        ),
        draft_attempt_key=pending.idempotency_key if pending is not None else None,
        attempt_type=attempt_type,
        eligible_at=_as_utc(state.eligible_at) if state else None,
        window_id=(pending.window_id if pending is not None else None)
        or (active_window.id if active_window is not None else None),
        phase=phase,
    )


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
        state.technique_id: state for state in session.scalars(select(CommandPracticeState)).all()
    }
    due: list[tuple[datetime, str, CommandPracticeState]] = []
    new_ids: list[str] = []
    for technique_id in catalog.techniques:
        state = states.get(technique_id)
        pending = _pending_attempt(session, technique_id)
        if pending is not None and pending.recall_completed_at is not None:
            if state is None:
                raise RuntimeError(f"pending command attempt has no state: {technique_id}")
            due.append((datetime.min.replace(tzinfo=UTC), technique_id, state))
            continue
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
    selected_new = _interleave_by_shell(new_ids, catalog)[:remaining_capacity]
    items: list[CommandPracticeItem] = []
    for due_at, technique_id, state in selected_due:
        items.append(
            _practice_item(
                session,
                catalog,
                technique_id,
                state,
                due_at=due_at,
                overdue=True,
                now=now,
            )
        )
    for technique_id in selected_new:
        state = states.get(technique_id)
        items.append(
            _practice_item(
                session,
                catalog,
                technique_id,
                state,
                due_at=None,
                overdue=False,
                now=now,
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
    now: datetime | None = None,
) -> CommandPracticeState:
    now = now or datetime.now(UTC)
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
            grading_policy_version=GRADING_POLICY_VERSION,
        )
        session.add(state)
    else:
        state.timezone = timezone
        if state.grading_policy_version < GRADING_POLICY_VERSION:
            state.eligible_at = now + HELP_COOLDOWN
            state.grading_policy_version = GRADING_POLICY_VERSION
    return state


def _begin_immediate(session: Session) -> None:
    if not session.in_transaction():
        session.execute(text("BEGIN IMMEDIATE"))


def _window_for_new_attempt(
    session: Session,
    *,
    state: CommandPracticeState,
    technique_id: str,
    challenge_version: int,
    now: datetime,
) -> AssessmentWindow:
    active = _active_window(session, technique_id)
    if active is not None:
        return active
    window_type: AttemptType = "assessment" if _assessment_allowed(state, now) else "rehearsal"
    window = AssessmentWindow(
        technique_id=technique_id,
        challenge_version=challenge_version,
        grading_policy_version=GRADING_POLICY_VERSION,
        window_type=window_type,
        opened_at=now,
        eligible_at=_as_utc(state.eligible_at) or now,
        advancement_applied=False,
        contaminated=False,
    )
    session.add(window)
    session.flush()
    return window


def _attempt_for(
    session: Session,
    catalog: CommandCatalog,
    attempt_key: str,
    technique_id: str,
    answer_shell: str,
    state: CommandPracticeState,
    now: datetime,
) -> CommandAttempt:
    attempt = session.scalar(
        select(CommandAttempt).where(CommandAttempt.idempotency_key == attempt_key)
    )
    challenge = catalog.challenge(technique_id)
    if attempt is None:
        window = _window_for_new_attempt(
            session,
            state=state,
            technique_id=technique_id,
            challenge_version=challenge.version,
            now=now,
        )
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
            window_id=window.id,
            attempt_type=window.window_type,
            structured_observation={},
            verification_status="verified",
            grader_version=GRADER_VERSION,
            grading_policy_version=GRADING_POLICY_VERSION,
        )
        attempt.shell = answer_shell
        session.add(attempt)
    elif attempt.technique_id != technique_id:
        raise AppError(
            409,
            "attempt_technique_mismatch",
            "Ключ попытки уже связан с другим приёмом.",
        )
    elif attempt.completed_at is None and attempt.challenge_version != challenge.version:
        raise AppError(
            409,
            "challenge_version_changed",
            "Условие задания изменилось. Ответ сохранён, начните актуальную версию.",
            {
                "attempt_challenge_version": attempt.challenge_version,
                "current_challenge_version": challenge.version,
                "saved_answer": attempt.answer,
            },
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
    _begin_immediate(session)
    state = _state_for(session, catalog, technique_id, timezone, now)
    attempt = _attempt_for(session, catalog, attempt_key, technique_id, answer_shell, state, now)
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
    now: datetime | None = None,
) -> CommandAttempt:
    now = now or datetime.now(UTC)
    _begin_immediate(session)
    state = _state_for(session, catalog, technique_id, timezone, now)
    attempt = _attempt_for(session, catalog, attempt_key, technique_id, answer_shell, state, now)
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
        _record_help_event(
            session,
            catalog,
            state=state,
            technique_id=technique_id,
            disclosure_key=f"hint:{attempt_key}:{level}",
            surface="hint",
            window_id=attempt.window_id,
            now=now,
        )
    state.current_help_levels = sorted(
        set(state.current_help_levels or []).union(attempt.revealed_help or [])
    )
    session.commit()
    session.refresh(attempt)
    return attempt


def _record_help_event(
    session: Session,
    catalog: CommandCatalog,
    *,
    state: CommandPracticeState,
    technique_id: str,
    disclosure_key: str,
    surface: Literal["hint", "technique_card", "mission_reference"],
    window_id: int | None,
    now: datetime,
) -> tuple[HelpEvent, bool]:
    existing = session.scalar(select(HelpEvent).where(HelpEvent.disclosure_key == disclosure_key))
    if existing is not None:
        return existing, True
    event = HelpEvent(
        disclosure_key=disclosure_key,
        technique_id=technique_id,
        challenge_version=catalog.challenge(technique_id).version,
        window_id=window_id,
        shown_at=now,
        surface=surface,
        scope="answer",
    )
    session.add(event)
    state.last_help_at = now
    cooldown = now + HELP_COOLDOWN
    current_eligible = _as_utc(state.eligible_at)
    if current_eligible is None or cooldown > current_eligible:
        state.eligible_at = cooldown
    if window_id is not None:
        window = session.get(AssessmentWindow, window_id)
        if window is not None:
            window.contaminated = True
    session.flush()
    return event, False


def reveal_command_reference(
    session: Session,
    catalog: CommandCatalog,
    *,
    technique_id: str,
    disclosure_key: str,
    surface: Literal["technique_card", "mission_reference"],
    timezone: str,
    now: datetime | None = None,
) -> ReferenceDisclosure:
    now = now or datetime.now(UTC)
    _begin_immediate(session)
    state = _state_for(session, catalog, technique_id, timezone, now)
    active = _active_window(session, technique_id)
    event, duplicate = _record_help_event(
        session,
        catalog,
        state=state,
        technique_id=technique_id,
        disclosure_key=disclosure_key,
        surface=surface,
        window_id=active.id if active is not None else None,
        now=now,
    )
    session.commit()
    session.refresh(event)
    return ReferenceDisclosure(
        technique=catalog.technique(technique_id),
        event_id=event.id,
        shown_at=_as_utc(event.shown_at) or now,
        duplicate=duplicate,
    )


def _completion_from_attempt(
    attempt: CommandAttempt,
    state: CommandPracticeState,
    *,
    duplicate: bool,
) -> CompletionResult:
    attempt_type: AttemptType = (
        "assessment" if attempt.attempt_type == "assessment" else "rehearsal"
    )
    return CompletionResult(
        attempt_id=attempt.id,
        technique_id=attempt.technique_id,
        reason=RecallReason(attempt.result),
        correct=attempt.result
        in {
            RecallReason.correct.value,
            RecallReason.correct_with_help.value,
        },
        independent=bool(attempt.interval_days is not None and attempt_type == "assessment"),
        observation_correct=attempt.observation_correct,
        next_due_at=_as_utc(attempt.next_due_at),
        interval_days=attempt.interval_days,
        retry_in_session=state.retry_in_session,
        duplicate=duplicate,
        verification_status=(
            "unverified" if attempt.verification_status == "unverified" else "verified"
        ),
        detail=attempt.error_kind or "Результат уже сохранён.",
        attempt_type=attempt_type,
        completed=attempt.completed_at is not None,
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
    _begin_immediate(session)
    state = _state_for(session, catalog, technique_id, timezone, now)
    attempt = _attempt_for(session, catalog, attempt_key, technique_id, answer_shell, state, now)
    if attempt.recall_completed_at is not None:
        result = _completion_from_attempt(attempt, state, duplicate=True)
        if attempt.completed_at is None and attempt.result in {
            RecallReason.correct.value,
            RecallReason.correct_with_help.value,
        }:
            challenge = catalog.challenge(technique_id)
            result.observation_example = challenge.observation.example_output
            result.observation_fields = [
                PublicObservationField(id=field.id, label=field.label)
                for field in challenge.observation.fields
            ]
        return result
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
    window = session.get(AssessmentWindow, attempt.window_id) if attempt.window_id else None
    if window is not None and window.contaminated and grade.correct:
        grade.reason = RecallReason.correct_with_help
        grade.independent = False
    attempt.shell = answer_shell
    attempt.answer = answer
    attempt.observation_answer = observation_answer
    attempt.dont_remember = dont_remember
    attempt.result = grade.reason.value
    attempt.error_kind = grade.detail
    attempt.verification_status = grade.verification_status
    attempt.grader_version = GRADER_VERSION
    attempt.grading_policy_version = GRADING_POLICY_VERSION
    if grade.verification_status == "unverified":
        state.draft_answer = answer
        state.draft_observation_answer = observation_answer
        state.draft_updated_at = now
        session.commit()
        session.refresh(attempt)
        return CompletionResult(
            attempt_id=attempt.id,
            technique_id=technique_id,
            reason=grade.reason,
            correct=False,
            independent=False,
            observation_correct=False,
            next_due_at=_as_utc(state.next_due_at),
            interval_days=None,
            retry_in_session=state.retry_in_session,
            verification_status="unverified",
            detail=grade.detail,
            attempt_type=("assessment" if attempt.attempt_type == "assessment" else "rehearsal"),
            completed=False,
        )
    attempt.recall_completed_at = now
    state.last_attempt_at = now
    state.draft_answer = answer
    state.draft_observation_answer = ""
    state.draft_updated_at = now
    interval_days: int | None = None
    clean_assessment = bool(
        grade.independent
        and attempt.attempt_type == "assessment"
        and window is not None
        and not window.contaminated
        and not window.advancement_applied
    )
    if clean_assessment:
        interval_days = RECALL_INTERVAL_DAYS[
            min(state.interval_index, len(RECALL_INTERVAL_DAYS) - 1)
        ]
        state.interval_index = min(state.interval_index + 1, len(RECALL_INTERVAL_DAYS))
        state.next_due_at = now + timedelta(days=interval_days)
        state.eligible_at = state.next_due_at
        state.retry_in_session = False
        state.recalled_without_help_at = now
        if window is not None:
            window.advancement_applied = True
    elif grade.correct and (attempt.revealed_help or (window and window.contaminated)):
        state.recalled_with_help_at = now
        state.next_due_at = now + timedelta(days=1)
        state.eligible_at = now + HELP_COOLDOWN
        state.retry_in_session = False
    elif not grade.correct:
        state.next_due_at = now + timedelta(days=1)
        state.eligible_at = now + HELP_COOLDOWN
        state.retry_in_session = True
        if window is not None:
            window.contaminated = True
            window.result = grade.reason.value
    if grade.correct and window is not None:
        window.closed_at = now
        window.result = grade.reason.value
    if not grade.correct:
        attempt.completed_at = now
    attempt.next_due_at = state.next_due_at
    attempt.interval_days = interval_days
    session.commit()
    session.refresh(attempt)
    return CompletionResult(
        attempt_id=attempt.id,
        technique_id=technique_id,
        reason=grade.reason,
        correct=grade.correct,
        independent=clean_assessment,
        observation_correct=False,
        next_due_at=_as_utc(state.next_due_at),
        interval_days=interval_days,
        retry_in_session=state.retry_in_session,
        verification_status="verified",
        detail=grade.detail,
        attempt_type="assessment" if attempt.attempt_type == "assessment" else "rehearsal",
        completed=not grade.correct,
        observation_example=challenge.observation.example_output if grade.correct else None,
        observation_fields=(
            [
                PublicObservationField(id=field.id, label=field.label)
                for field in challenge.observation.fields
            ]
            if grade.correct
            else []
        ),
    )


def _grade_structured_observation(
    values: dict[str, str], contract: ObservationContract
) -> dict[str, str]:
    errors: dict[str, str] = {}
    expected_ids = {field.id for field in contract.fields}
    for field_id in sorted(set(values).difference(expected_ids)):
        errors[field_id] = "Поле не входит в контракт этого задания."
    for field in contract.fields:
        value = str(values.get(field.id, "")).strip()
        if not value:
            errors[field.id] = "Заполните обязательный факт из показанного вывода."
            continue
        exact = any(value.casefold() == item.casefold() for item in field.accepted_values)
        pattern = any(
            re.fullmatch(item, value, re.IGNORECASE) is not None for item in field.accepted_patterns
        )
        if not exact and not pattern:
            errors[field.id] = f"Факт «{field.label}» не подтверждается примером вывода."
    return errors


def complete_command_observation(
    session: Session,
    catalog: CommandCatalog,
    *,
    attempt_key: str,
    technique_id: str,
    structured_observation: dict[str, str],
    free_text: str,
    timezone: str,
    now: datetime | None = None,
) -> ObservationCompletionResult:
    now = now or datetime.now(UTC)
    _begin_immediate(session)
    state = _state_for(session, catalog, technique_id, timezone, now)
    attempt = session.scalar(
        select(CommandAttempt).where(CommandAttempt.idempotency_key == attempt_key)
    )
    if attempt is None or attempt.technique_id != technique_id:
        raise AppError(404, "command_attempt_not_found", "Попытка команды не найдена.")
    challenge = catalog.challenge(technique_id)
    if attempt.challenge_version != challenge.version:
        raise AppError(
            409,
            "challenge_version_changed",
            "Условие задания изменилось. Начните актуальную версию.",
        )
    if attempt.recall_completed_at is None or attempt.result not in {
        RecallReason.correct.value,
        RecallReason.correct_with_help.value,
    }:
        raise AppError(409, "recall_not_completed", "Сначала зафиксируйте ответ на команду.")
    if attempt.observation_completed_at is not None:
        return ObservationCompletionResult(
            attempt_id=attempt.id,
            technique_id=technique_id,
            observation_correct=attempt.observation_correct,
            completed=True,
        )
    errors = _grade_structured_observation(structured_observation, challenge.observation)
    attempt.structured_observation = dict(structured_observation)
    attempt.observation_answer = free_text
    state.draft_observation_answer = free_text
    state.draft_updated_at = now
    if errors:
        session.commit()
        return ObservationCompletionResult(
            attempt_id=attempt.id,
            technique_id=technique_id,
            observation_correct=False,
            field_errors=errors,
            completed=False,
        )
    attempt.observation_correct = True
    attempt.observation_completed_at = now
    attempt.completed_at = now
    state.output_interpreted_at = now
    state.practice_cycle += 1
    state.current_help_levels = []
    state.draft_answer = ""
    state.draft_observation_answer = ""
    state.draft_updated_at = now
    state.challenge_version = challenge.version
    state.data_version = catalog.version
    state.grading_policy_version = GRADING_POLICY_VERSION
    session.commit()
    return ObservationCompletionResult(
        attempt_id=attempt.id,
        technique_id=technique_id,
        observation_correct=True,
        completed=True,
    )
