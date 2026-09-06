from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models import MissionRun
from .command_practice import CommandCatalog
from .mission_grader import MissionGradeStatus, MissionGradingContract, grade_mission


class PreparedDataEntry(BaseModel):
    path: str = Field(min_length=1, max_length=240, pattern=r"^[^/].*$")
    kind: Literal["directory", "text", "note"]
    content: str = Field(default="", max_length=4000)


class MissionVariant(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    scenario: str = Field(min_length=1)
    prepared_data: list[PreparedDataEntry] = Field(min_length=2)
    grading: MissionGradingContract


class InvestigationMission(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    title: str = Field(min_length=1)
    story: str = Field(min_length=1)
    allowed_environment: str = Field(min_length=1)
    prepared_data_description: str = Field(min_length=1)
    required_actions: list[str] = Field(min_length=1)
    final_artifact_prompt: str = Field(min_length=1)
    explanation_prompt: str = Field(min_length=1)
    technique_ids: list[str] = Field(min_length=1)
    variant_rule: str = Field(min_length=1)
    requires_free_text: bool = True
    version: int = Field(ge=1)
    variants: list[MissionVariant] = Field(min_length=2)

    @model_validator(mode="after")
    def unique_variant_ids(self) -> InvestigationMission:
        variant_ids = [item.id for item in self.variants]
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError(f"duplicate mission variant id in {self.id}")
        return self


class MissionCatalogDocument(BaseModel):
    version: int = Field(ge=1)
    missions: list[InvestigationMission] = Field(min_length=2)


class MissionPlanItem(BaseModel):
    mission_id: str
    title: str
    story: str
    allowed_environment: str
    prepared_data_description: str
    required_actions: list[str]
    final_artifact_prompt: str
    explanation_prompt: str
    technique_ids: list[str]
    technique_refs: list[dict[str, str]]
    variant_rule: str
    requires_free_text: bool
    version: int
    variant_id: str
    scenario: str
    prepared_data: list[PreparedDataEntry]
    fact_fields: list[dict[str, str | bool]]
    draft_attempt_key: str | None
    draft_artifact: str
    draft_explanation: str
    draft_structured_facts: dict[str, str]


class MissionPlan(BaseModel):
    items: list[MissionPlanItem]


class MissionCompletionResult(BaseModel):
    run_id: int
    mission_id: str
    variant_id: str
    status: MissionGradeStatus
    reason: str
    explanation_accepted: bool
    debrief: str
    evidence_kind: str
    duplicate: bool = False
    field_errors: dict[str, str] = Field(default_factory=dict)
    free_text_review_status: Literal["not_assessed"] = "not_assessed"


class MissionCatalog:
    def __init__(self, directory: Path, command_catalog: CommandCatalog):
        self.directory = directory
        self.command_catalog = command_catalog
        self.version = 0
        self.missions: dict[str, InvestigationMission] = {}
        self.reload()

    def reload(self) -> None:
        paths = sorted(self.directory.glob("*.yaml"))
        if not paths:
            raise ValueError(f"no mission catalog YAML found in {self.directory}")
        if len(paths) != 1:
            raise ValueError("mission catalog must be stored in one canonical YAML file")
        payload = yaml.safe_load(paths[0].read_text(encoding="utf-8"))
        document = MissionCatalogDocument.model_validate(payload)
        missions = {item.id: item for item in document.missions}
        if len(missions) != len(document.missions):
            raise ValueError("duplicate investigation mission id")
        for mission in missions.values():
            unknown = set(mission.technique_ids).difference(self.command_catalog.techniques)
            if unknown:
                joined = ", ".join(sorted(unknown))
                raise ValueError(f"{mission.id}: unknown command technique ids: {joined}")
        self.version = document.version
        self.missions = missions

    def mission(self, mission_id: str) -> InvestigationMission:
        mission = self.missions.get(mission_id)
        if mission is None:
            raise AppError(
                404, "mission_not_found", "Миссия не найдена.", {"mission_id": mission_id}
            )
        return mission

    def variant(self, mission_id: str, variant_id: str) -> MissionVariant:
        mission = self.mission(mission_id)
        for variant in mission.variants:
            if variant.id == variant_id:
                return variant
        raise AppError(
            404,
            "mission_variant_not_found",
            "Вариант данных миссии не найден.",
            {"mission_id": mission_id, "variant_id": variant_id},
        )


def _latest_draft(session: Session, mission_id: str) -> MissionRun | None:
    return session.scalar(
        select(MissionRun)
        .where(MissionRun.mission_id == mission_id, MissionRun.completed_at.is_(None))
        .order_by(MissionRun.draft_updated_at.desc(), MissionRun.id.desc())
    )


def _planned_variant(
    session: Session,
    mission: InvestigationMission,
) -> tuple[MissionVariant, MissionRun | None]:
    draft = _latest_draft(session, mission.id)
    if draft is not None:
        return next(item for item in mission.variants if item.id == draft.data_variant), draft
    completed = session.scalar(
        select(func.count())
        .select_from(MissionRun)
        .where(MissionRun.mission_id == mission.id, MissionRun.completed_at.is_not(None))
    )
    return mission.variants[int(completed or 0) % len(mission.variants)], None


def plan_missions(session: Session, catalog: MissionCatalog) -> MissionPlan:
    items: list[MissionPlanItem] = []
    for mission in catalog.missions.values():
        variant, draft = _planned_variant(session, mission)
        items.append(
            MissionPlanItem(
                mission_id=mission.id,
                title=mission.title,
                story=mission.story,
                allowed_environment=mission.allowed_environment,
                prepared_data_description=mission.prepared_data_description,
                required_actions=mission.required_actions,
                final_artifact_prompt=mission.final_artifact_prompt,
                explanation_prompt=mission.explanation_prompt,
                technique_ids=mission.technique_ids,
                technique_refs=[
                    {
                        "id": item,
                        "label": catalog.command_catalog.technique(item).family,
                        "shell": catalog.command_catalog.technique(item).shell,
                    }
                    for item in mission.technique_ids
                ],
                variant_rule=mission.variant_rule,
                requires_free_text=mission.requires_free_text,
                version=mission.version,
                variant_id=variant.id,
                scenario=variant.scenario,
                prepared_data=variant.prepared_data,
                fact_fields=[
                    {"id": field.id, "label": field.label, "required": True}
                    for field in variant.grading.facts
                ],
                draft_attempt_key=draft.idempotency_key if draft else None,
                draft_artifact=draft.declared_artifact if draft else "",
                draft_explanation=draft.explanation if draft else "",
                draft_structured_facts=dict(draft.structured_facts or {}) if draft else {},
            )
        )
    return MissionPlan(items=items)


def _run_for(
    session: Session,
    catalog: MissionCatalog,
    *,
    attempt_key: str,
    mission_id: str,
    variant_id: str,
    now: datetime,
) -> MissionRun:
    mission = catalog.mission(mission_id)
    run = session.scalar(select(MissionRun).where(MissionRun.idempotency_key == attempt_key))
    if run is not None:
        if run.mission_id != mission_id or run.data_variant != variant_id:
            raise AppError(
                409,
                "mission_attempt_mismatch",
                "Ключ попытки уже связан с другой миссией или вариантом данных.",
            )
        return run
    planned_variant, active_draft = _planned_variant(session, mission)
    if active_draft is not None:
        raise AppError(
            409,
            "mission_draft_exists",
            "Для этой миссии уже есть черновик. Продолжите сохранённую попытку.",
            {"attempt_key": active_draft.idempotency_key},
        )
    if variant_id != planned_variant.id:
        raise AppError(
            409,
            "mission_variant_stale",
            "Вариант данных изменился. Обновите миссию перед отправкой.",
            {"variant_id": planned_variant.id},
        )
    run = MissionRun(
        idempotency_key=attempt_key,
        mission_id=mission.id,
        mission_version=mission.version,
        data_version=catalog.version,
        data_variant=planned_variant.id,
        declared_artifact="",
        explanation="",
        grader_status="draft",
        evidence_kind="mission_final_artifact",
        structured_facts={},
        free_text_review_status="not_assessed",
        grading_policy_version=2,
        draft_updated_at=now,
    )
    session.add(run)
    return run


def save_mission_draft(
    session: Session,
    catalog: MissionCatalog,
    *,
    attempt_key: str,
    mission_id: str,
    variant_id: str,
    artifact: str,
    explanation: str,
    structured_facts: dict[str, str],
    now: datetime | None = None,
) -> MissionRun:
    now = now or datetime.now(UTC)
    run = _run_for(
        session,
        catalog,
        attempt_key=attempt_key,
        mission_id=mission_id,
        variant_id=variant_id,
        now=now,
    )
    if run.completed_at is None:
        run.declared_artifact = artifact
        run.explanation = explanation
        run.structured_facts = dict(structured_facts)
        run.draft_updated_at = now
        session.commit()
        session.refresh(run)
    return run


def _completion_from_run(
    run: MissionRun,
    variant: MissionVariant,
    *,
    duplicate: bool,
) -> MissionCompletionResult:
    return MissionCompletionResult(
        run_id=run.id,
        mission_id=run.mission_id,
        variant_id=run.data_variant,
        status=MissionGradeStatus(run.grader_status),
        reason=run.grader_reason or "Результат миссии сохранён.",
        explanation_accepted=run.explanation_accepted,
        debrief=variant.grading.explanation.debrief,
        evidence_kind=run.evidence_kind,
        duplicate=duplicate,
        free_text_review_status="not_assessed",
    )


def complete_mission_run(
    session: Session,
    catalog: MissionCatalog,
    *,
    attempt_key: str,
    mission_id: str,
    variant_id: str,
    artifact: str,
    explanation: str,
    structured_facts: dict[str, str],
    now: datetime | None = None,
) -> MissionCompletionResult:
    now = now or datetime.now(UTC)
    run = _run_for(
        session,
        catalog,
        attempt_key=attempt_key,
        mission_id=mission_id,
        variant_id=variant_id,
        now=now,
    )
    variant = catalog.variant(mission_id, variant_id)
    if run.completed_at is not None:
        return _completion_from_run(run, variant, duplicate=True)
    grade = grade_mission(artifact, structured_facts, explanation, variant.grading)
    run.declared_artifact = artifact
    run.explanation = explanation
    run.structured_facts = dict(structured_facts)
    run.grader_status = grade.status.value
    run.grader_reason = grade.reason
    run.explanation_accepted = grade.explanation_accepted
    run.free_text_review_status = "not_assessed"
    run.grading_policy_version = 2
    run.completed_at = now
    run.draft_updated_at = now
    session.commit()
    session.refresh(run)
    result = _completion_from_run(run, variant, duplicate=False)
    result.field_errors = grade.field_errors
    return result
