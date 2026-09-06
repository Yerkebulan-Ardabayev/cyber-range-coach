from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .services.recall_grader import Shell


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str


class CheckResult(ApiModel):
    id: str
    status: Literal["ok", "warning", "blocked", "unavailable"]
    title: str
    detail: str
    action: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class PreflightResponse(ApiModel):
    ready: bool
    platform: str
    windows_supported: bool
    checks: list[CheckResult]
    generated_at: datetime


class NetworkInterface(ApiModel):
    address: str
    private: bool
    loopback: bool


class NetworkResponse(ApiModel):
    bind_host: str
    port: int
    lan_mode: bool
    tls_enabled: bool
    interfaces: list[NetworkInterface]
    academy_urls: list[str]


class PublishedPort(ApiModel):
    container_port: int
    protocol: Literal["tcp", "udp"]
    host_ip: str
    host_port: int
    loopback_endpoint: str | None = None
    exposure: Literal["loopback", "lan", "unknown"]


class DiscoveredTarget(ApiModel):
    container_id: str
    name: str
    image: str
    image_digest: str
    state: str
    health: str | None = None
    started_at: str | None = None
    ports: list[PublishedPort]
    detected_kind: Literal["webgoat", "juice_shop", "generic"]
    warnings: list[str] = Field(default_factory=list)


class TargetCreate(ApiModel):
    container_id: str = Field(min_length=12, max_length=64, pattern=r"^[0-9a-fA-F]+$")
    container_port: int = Field(ge=1, le=65535)
    protocol: Literal["tcp"] = "tcp"
    display_name: str = Field(min_length=2, max_length=160)
    allowed_curriculum_tags: list[str] = Field(default_factory=list, max_length=20)


class TargetResponse(ApiModel):
    id: int
    display_name: str
    provider: str
    container_reference: str
    container_port: int
    image_digest: str
    host_endpoint: str
    health_check: dict[str, Any]
    reset_policy: str
    fingerprint: str
    allowed_curriculum_tags: list[str]
    exposure_warnings: list[str]
    approved_at: datetime
    last_verified_at: datetime | None


class TargetVerifyResponse(ApiModel):
    target_id: int
    reachable: bool
    tcp_connected: bool
    http_response_received: bool
    http_status: int | None = None
    detail: str
    checked_at: datetime


class RelayStartRequest(ApiModel):
    linux_vm_ip: str


class RelayResponse(ApiModel):
    target_id: int
    active: bool
    bind_host: str | None = None
    connect_host: str | None = None
    port: int | None = None
    allowed_source_ip: str | None = None
    upstream: str | None = None


class LinuxHostCreate(ApiModel):
    name: str = Field(default="Linux VM", min_length=2, max_length=120)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    relay_source_ip: str | None = Field(default=None, max_length=45)
    username: str = Field(default="student", min_length=1, max_length=80)
    runner_username: str = Field(default="range-runner", min_length=1, max_length=80)

    @field_validator("username", "runner_username")
    @classmethod
    def safe_linux_username(cls, value: str) -> str:
        if not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("username contains unsupported characters")
        if value in {"root", "administrator"}:
            raise ValueError("privileged account is not allowed")
        return value

    @field_validator("relay_source_ip")
    @classmethod
    def safe_relay_source_ip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        address = ipaddress.ip_address(value)
        if address.version != 4 or address.is_loopback or address.is_unspecified:
            raise ValueError("relay_source_ip must be a non-loopback IPv4 address")
        return str(address)


class LinuxHostResponse(ApiModel):
    id: int
    name: str
    host: str
    port: int
    relay_source_ip: str | None
    username: str
    runner_username: str
    public_key: str
    runner_public_key: str
    host_key_fingerprint: str | None
    confirmed: bool
    last_preflight_at: datetime | None


class LinuxProbeResponse(ApiModel):
    host_id: int
    tcp_reachable: bool
    ssh_authenticated: bool
    fingerprint: str | None
    host_key: str | None
    detail: str


class WslUbuntuPrepareResponse(ApiModel):
    status: Literal["ready_for_probe", "sudo_password_required", "blocked"]
    distribution: str | None
    host: str
    port: int
    relay_source_ip: str | None = None
    ssh_reachable: bool
    detail: str
    sudo_command: str | None = None


class FingerprintConfirm(ApiModel):
    fingerprint: str = Field(min_length=8, max_length=255)


class SessionPlanRequest(ApiModel):
    duration_minutes: Literal[15, 45, 90]


class LessonSummary(ApiModel):
    id: str
    title: str
    summary: str
    estimated_minutes: int
    skill_id: str
    stage: str
    target_tags: list[str]


class SessionPlanResponse(ApiModel):
    duration_minutes: int
    lessons: list[LessonSummary]
    rationale: list[str]


class SessionCreate(SessionPlanRequest):
    lesson_ids: list[str] | None = None


class SessionResponse(ApiModel):
    id: int
    duration_minutes: int
    status: str
    lesson_ids: list[str]
    current_lesson_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class LabRunCreate(ApiModel):
    session_id: int
    lesson_id: str
    target_id: int | None = None
    prediction: str = Field(min_length=3, max_length=4000)


class LabRunResponse(ApiModel):
    id: int
    session_id: int
    lesson_id: str
    skill_id: str
    target_id: int | None
    target_fingerprint: str | None
    status: str
    prediction: str | None
    explanation: str | None
    tutor_feedback_at: datetime | None
    tutor_question: str | None
    tutor_explanation: str | None
    correction: str | None
    transcript: str
    terminal_inputs: list[str]
    terminal_input_offsets: list[int]
    terminal_input_kinds: list[str]
    input_integrity: str
    input_integrity_reason: str | None
    terminal_session_id: str | None
    grader_status: str | None
    grader_report: dict[str, Any]
    relay_port: int | None
    created_at: datetime
    stopped_at: datetime | None


class ExplanationRequest(ApiModel):
    text: str = Field(min_length=3, max_length=8000)


class CorrectionRequest(ApiModel):
    corrected_conclusion: str = Field(min_length=12, max_length=4000)
    limitation: str = Field(min_length=8, max_length=2000)
    next_test: str = Field(min_length=8, max_length=2000)


class LabReset(ApiModel):
    prediction: str = Field(min_length=3, max_length=4000)


class GradeResponse(ApiModel):
    run_id: int
    status: Literal["passed", "failed", "needs_evidence"]
    checks: list[dict[str, Any]]
    explanation_prompt: str
    evidence_stage: str | None = None


class TutorFeedbackRequest(ApiModel):
    run_id: int


class TutorFeedbackResponse(ApiModel):
    provider: str
    available: bool
    question: str
    explanation: str
    missed: list[str]
    caution: str | None = None
    redactions: int = 0


class EvidenceResponse(ApiModel):
    id: int
    run_id: int
    skill_id: str
    stage: str
    source_type: str
    source_id: str
    target_fingerprint: str | None
    fact: str
    grader_decision: str
    created_at: datetime


class ReviewResponse(ApiModel):
    id: int
    skill_id: str
    lesson_id: str
    due_at: datetime
    reason: str
    completed_at: datetime | None


class CommandAttemptBase(ApiModel):
    technique_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]+$")
    shell: Shell
    timezone: str = Field(min_length=1, max_length=80)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("unknown IANA timezone") from error
        return value


class CommandDraftRequest(CommandAttemptBase):
    answer: str = Field(max_length=4000)
    observation_answer: str = Field(default="", max_length=4000)


class CommandHintRequest(CommandAttemptBase):
    pass


class CommandCompleteRequest(CommandAttemptBase):
    answer: str = Field(default="", max_length=4000)
    observation_answer: str = Field(default="", max_length=4000)
    dont_remember: bool = False


class CommandObservationRequest(ApiModel):
    technique_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]+$")
    timezone: str = Field(min_length=1, max_length=80)
    structured_observation: dict[str, str] = Field(default_factory=dict)
    free_text: str = Field(default="", max_length=4000)

    @field_validator("timezone")
    @classmethod
    def known_observation_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("unknown IANA timezone") from error
        return value


class CommandReferenceRevealRequest(ApiModel):
    disclosure_key: str = Field(min_length=16, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    timezone: str = Field(min_length=1, max_length=80)
    surface: Literal["technique_card", "mission_reference"]


class MissionAttemptBase(ApiModel):
    mission_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]+$")
    variant_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]+$")


class MissionDraftRequest(MissionAttemptBase):
    artifact: str = Field(max_length=4000)
    explanation: str = Field(default="", max_length=4000)
    structured_facts: dict[str, str] = Field(default_factory=dict)


class MissionCompleteRequest(MissionAttemptBase):
    artifact: str = Field(default="", max_length=4000)
    explanation: str = Field(default="", max_length=4000)
    structured_facts: dict[str, str] = Field(default_factory=dict)


class NoteCreate(ApiModel):
    title: str = Field(default="Field note", min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=100_000)
    lesson_id: str | None = None
    run_id: int | None = None


class NoteResponse(ApiModel):
    id: int
    title: str
    body: str
    lesson_id: str | None
    run_id: int | None
    source_v1_id: int | None
    source_hash: str | None
    created_at: datetime
    updated_at: datetime


class PairingCreate(ApiModel):
    role: Literal["operator", "viewer"]


class PairingCreated(ApiModel):
    token: str
    role: str
    expires_at: datetime
    certificate_fingerprint: str


class PairingConsume(ApiModel):
    token: str = Field(min_length=20, max_length=200)
    device_name: str = Field(min_length=2, max_length=120)
    confirmed_fingerprint: str = Field(min_length=3, max_length=255)


class PairedDevice(ApiModel):
    id: int
    name: str
    role: str
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


class PairingResult(ApiModel):
    device: PairedDevice
    csrf_token: str


class StudioSourceResponse(ApiModel):
    id: int
    original_name: str
    stored_name: str
    media_type: str
    sha256: str
    size_bytes: int
    extractor: str
    immutable_ok: bool
    created_at: datetime
    block_count: int


class DraftCreate(ApiModel):
    title: str = Field(min_length=2, max_length=200)
    source_ids: list[int] = Field(min_length=1, max_length=20)


class DraftUpdate(ApiModel):
    title: str = Field(min_length=2, max_length=200)
    content: dict[str, Any]


class DraftResponse(ApiModel):
    id: int
    title: str
    source_ids: list[int]
    covered_block_ids: list[int]
    content: dict[str, Any]
    status: str
    validation_report: dict[str, Any]
    created_at: datetime
    published_at: datetime | None
