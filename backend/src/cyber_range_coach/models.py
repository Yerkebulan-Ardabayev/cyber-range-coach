from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class DeviceRole(StrEnum):
    owner = "owner"
    operator = "operator"
    viewer = "viewer"


class SkillStage(StrEnum):
    introduced = "introduced"
    guided = "guided"
    independent = "independent"
    transfer = "transfer"


class SessionStatus(StrEnum):
    planned = "planned"
    active = "active"
    completed = "completed"
    abandoned = "abandoned"


class RunStatus(StrEnum):
    active = "active"
    completed = "completed"
    stopped = "stopped"
    abandoned = "abandoned"


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    requested_role: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TargetProfile(Base):
    __tablename__ = "target_profiles"
    __table_args__ = (
        UniqueConstraint(
            "container_reference",
            "container_port",
            name="uq_target_container_port",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(40), default="docker_desktop")
    container_reference: Mapped[str] = mapped_column(String(128))
    container_port: Mapped[int] = mapped_column(Integer)
    image_digest: Mapped[str] = mapped_column(String(255))
    host_endpoint: Mapped[str] = mapped_column(String(500))
    health_check: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reset_policy: Mapped[str] = mapped_column(String(30), default="external")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    allowed_curriculum_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    exposure_warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LinuxHost(Base):
    __tablename__ = "linux_hosts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Linux VM")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=22)
    relay_source_ip: Mapped[str | None] = mapped_column(String(45))
    username: Mapped[str] = mapped_column(String(80), default="student")
    runner_username: Mapped[str] = mapped_column(String(80), default="range-runner")
    encrypted_private_key: Mapped[str] = mapped_column(Text)
    public_key: Mapped[str] = mapped_column(Text)
    encrypted_runner_private_key: Mapped[str] = mapped_column(Text)
    runner_public_key: Mapped[str] = mapped_column(Text)
    pending_host_key: Mapped[str | None] = mapped_column(Text)
    host_key: Mapped[str | None] = mapped_column(Text)
    host_key_fingerprint: Mapped[str | None] = mapped_column(String(255))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_preflight_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningSession(Base):
    __tablename__ = "learning_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=SessionStatus.planned.value)
    lesson_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_lesson_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list[LabRun]] = relationship(back_populates="session")


class LabRun(Base):
    __tablename__ = "lab_runs"
    __table_args__ = (
        Index(
            "uq_lab_runs_one_active",
            "status",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    lesson_id: Mapped[str] = mapped_column(String(120), index=True)
    skill_id: Mapped[str] = mapped_column(String(120), index=True)
    target_id: Mapped[int | None] = mapped_column(ForeignKey("target_profiles.id"))
    target_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.active.value)
    prediction: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    tutor_feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tutor_question: Mapped[str | None] = mapped_column(Text)
    tutor_explanation: Mapped[str | None] = mapped_column(Text)
    correction: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str] = mapped_column(Text, default="")
    terminal_inputs: Mapped[list[str]] = mapped_column(JSON, default=list)
    terminal_input_offsets: Mapped[list[int]] = mapped_column(JSON, default=list)
    terminal_input_kinds: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_integrity: Mapped[str] = mapped_column(String(30), default="unverified")
    input_integrity_reason: Mapped[str | None] = mapped_column(String(80))
    terminal_session_id: Mapped[str | None] = mapped_column(String(80))
    grader_status: Mapped[str | None] = mapped_column(String(30))
    grader_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # The learner opened the hidden command of a ladder step 2 or 3.
    help_used: Mapped[bool] = mapped_column(Boolean, default=False)
    help_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    relay_port: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[LearningSession] = relationship(back_populates="runs")
    target: Mapped[TargetProfile | None] = relationship()


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("run_id", "skill_id", name="uq_evidence_run_skill"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("lab_runs.id"), index=True)
    skill_id: Mapped[str] = mapped_column(String(120), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    source_type: Mapped[str] = mapped_column(String(40), default="terminal")
    source_id: Mapped[str] = mapped_column(String(120))
    target_fingerprint: Mapped[str | None] = mapped_column(String(64))
    fact: Mapped[str] = mapped_column(Text)
    grader_decision: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SkillState(Base):
    __tablename__ = "skill_states"

    skill_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    stage: Mapped[str] = mapped_column(String(20), default=SkillStage.introduced.value)
    successful_fingerprints: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(120), index=True)
    lesson_id: Mapped[str] = mapped_column(String(120))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason: Mapped[str] = mapped_column(String(255))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommandPracticeState(Base):
    __tablename__ = "command_practice_states"

    technique_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    challenge_version: Mapped[int] = mapped_column(Integer)
    data_version: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(80))
    practice_cycle: Mapped[int] = mapped_column(Integer, default=0)
    current_help_levels: Mapped[list[int]] = mapped_column(JSON, default=list)
    interval_index: Mapped[int] = mapped_column(Integer, default=0)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    retry_in_session: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    draft_answer: Mapped[str] = mapped_column(Text, default="")
    draft_observation_answer: Mapped[str] = mapped_column(Text, default="")
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recalled_without_help_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recalled_with_help_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_interpreted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_in_environment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_variant_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_help_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grading_policy_version: Mapped[int] = mapped_column(Integer, default=2)


class AssessmentWindow(Base):
    __tablename__ = "assessment_windows"
    __table_args__ = (
        Index(
            "uq_assessment_windows_active_technique",
            "technique_id",
            unique=True,
            sqlite_where=text("closed_at IS NULL AND window_type = 'assessment'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    technique_id: Mapped[str] = mapped_column(String(120), index=True)
    challenge_version: Mapped[int] = mapped_column(Integer)
    grading_policy_version: Mapped[int] = mapped_column(Integer, default=2)
    window_type: Mapped[str] = mapped_column(String(20), default="assessment")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    eligible_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    result: Mapped[str | None] = mapped_column(String(40))
    advancement_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    contaminated: Mapped[bool] = mapped_column(Boolean, default=False)


class HelpEvent(Base):
    __tablename__ = "help_events"
    __table_args__ = (UniqueConstraint("disclosure_key", name="uq_help_events_disclosure_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    disclosure_key: Mapped[str] = mapped_column(String(120))
    technique_id: Mapped[str] = mapped_column(String(120), index=True)
    challenge_version: Mapped[int] = mapped_column(Integer)
    window_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_windows.id"), index=True)
    shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    surface: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(40), default="answer")


class CommandAttempt(Base):
    __tablename__ = "command_attempts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_command_attempt_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    technique_id: Mapped[str] = mapped_column(String(120), index=True)
    challenge_version: Mapped[int] = mapped_column(Integer)
    data_version: Mapped[int] = mapped_column(Integer)
    practice_cycle: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    shell: Mapped[str] = mapped_column(String(30))
    answer: Mapped[str] = mapped_column(Text, default="")
    observation_answer: Mapped[str] = mapped_column(Text, default="")
    revealed_help: Mapped[list[int]] = mapped_column(JSON, default=list)
    error_kind: Mapped[str | None] = mapped_column(String(40))
    result: Mapped[str] = mapped_column(String(40), default="draft")
    evidence_kind: Mapped[str] = mapped_column(String(40), default="recall")
    observation_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    dont_remember: Mapped[bool] = mapped_column(Boolean, default=False)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interval_days: Mapped[int | None] = mapped_column(Integer)
    window_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_windows.id"), index=True)
    attempt_type: Mapped[str] = mapped_column(String(20), default="assessment")
    recall_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    structured_observation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification_status: Mapped[str] = mapped_column(String(30), default="verified")
    grader_version: Mapped[int] = mapped_column(Integer, default=2)
    grading_policy_version: Mapped[int] = mapped_column(Integer, default=2)


class MissionRun(Base):
    __tablename__ = "mission_runs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_mission_run_idempotency_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    mission_id: Mapped[str] = mapped_column(String(120), index=True)
    mission_version: Mapped[int] = mapped_column(Integer)
    data_version: Mapped[int] = mapped_column(Integer)
    data_variant: Mapped[str] = mapped_column(String(120))
    declared_artifact: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    grader_status: Mapped[str] = mapped_column(String(30), default="draft")
    grader_reason: Mapped[str | None] = mapped_column(Text)
    explanation_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_kind: Mapped[str] = mapped_column(String(40), default="mission_final_artifact")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    structured_facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    free_text_review_status: Mapped[str] = mapped_column(String(30), default="not_assessed")
    grading_policy_version: Mapped[int] = mapped_column(Integer, default=2)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="Field note")
    body: Mapped[str] = mapped_column(Text)
    lesson_id: Mapped[str | None] = mapped_column(String(120))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("lab_runs.id"))
    source_v1_id: Mapped[int | None] = mapped_column(Integer)
    source_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudioSource(Base):
    __tablename__ = "studio_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    media_type: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    extractor: Mapped[str] = mapped_column(String(80))
    immutable_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    blocks: Mapped[list[SourceBlock]] = relationship(back_populates="source")


class SourceBlock(Base):
    __tablename__ = "source_blocks"
    __table_args__ = (UniqueConstraint("source_id", "ordinal", name="uq_source_block"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("studio_sources.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    locator: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)

    source: Mapped[StudioSource] = relationship(back_populates="blocks")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    source_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    covered_block_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
