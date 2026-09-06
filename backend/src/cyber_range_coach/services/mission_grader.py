from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class MissionGradeStatus(StrEnum):
    solved = "solved"
    wrong_artifact = "wrong_artifact"
    unexplained = "unexplained"
    needs_review = "needs_review"


class MissionArtifactContract(BaseModel):
    accepted_values: list[str] = Field(min_length=1)
    accepted_patterns: list[str] = Field(default_factory=list)
    review_patterns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_patterns(self) -> MissionArtifactContract:
        for pattern in [*self.accepted_patterns, *self.review_patterns]:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"invalid mission artifact pattern: {pattern}") from error
        return self


class MissionExplanationContract(BaseModel):
    expected_concepts: list[list[str]] = Field(min_length=1)
    debrief: str = Field(min_length=1)


class MissionFactContract(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    label: str = Field(min_length=1)
    accepted_values: list[str] = Field(min_length=1)
    accepted_patterns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_patterns(self) -> MissionFactContract:
        for pattern in self.accepted_patterns:
            re.compile(pattern)
        return self


class MissionGradingContract(BaseModel):
    artifact: MissionArtifactContract
    facts: list[MissionFactContract] = Field(min_length=1)
    explanation: MissionExplanationContract


class MissionGrade(BaseModel):
    status: MissionGradeStatus
    reason: str
    explanation_accepted: bool
    field_errors: dict[str, str] = Field(default_factory=dict)
    free_text_review_status: str = "not_assessed"


def grade_mission(
    artifact: str | None,
    structured_facts: dict[str, str] | None,
    explanation: str | None,
    contract: MissionGradingContract,
) -> MissionGrade:
    """Grade a declared result only. The learner input is never executed."""
    declared_artifact = (artifact or "").strip()
    del explanation
    facts = structured_facts or {}
    if not declared_artifact:
        return MissionGrade(
            status=MissionGradeStatus.wrong_artifact,
            reason="Конечный артефакт не указан.",
            explanation_accepted=False,
        )
    known_artifact = declared_artifact in contract.artifact.accepted_values or any(
        re.fullmatch(pattern, declared_artifact) is not None
        for pattern in contract.artifact.accepted_patterns
    )
    if not known_artifact:
        if any(
            re.fullmatch(pattern, declared_artifact) is not None
            for pattern in contract.artifact.review_patterns
        ):
            return MissionGrade(
                status=MissionGradeStatus.needs_review,
                reason="Формат похож на возможный вариант, но его нет в контракте миссии.",
                explanation_accepted=False,
            )
        return MissionGrade(
            status=MissionGradeStatus.wrong_artifact,
            reason="Заявленный артефакт не подтверждается подготовленными данными.",
            explanation_accepted=False,
        )
    field_errors: dict[str, str] = {}
    expected_ids = {field.id for field in contract.facts}
    for field_id in sorted(set(facts).difference(expected_ids)):
        field_errors[field_id] = "Поле не входит в контракт этого варианта."
    missing = False
    for field in contract.facts:
        value = str(facts.get(field.id, "")).strip()
        if not value:
            missing = True
            field_errors[field.id] = "Заполните обязательный факт из публичного снимка."
            continue
        exact = any(value.casefold() == item.casefold() for item in field.accepted_values)
        pattern = any(
            re.fullmatch(item, value, re.IGNORECASE) is not None for item in field.accepted_patterns
        )
        if not exact and not pattern:
            field_errors[field.id] = f"Факт «{field.label}» не связан с выбранным вариантом."
    if field_errors:
        return MissionGrade(
            status=(
                MissionGradeStatus.unexplained if missing else MissionGradeStatus.wrong_artifact
            ),
            reason=(
                "Артефакт найден, но обязательные структурированные факты не заполнены."
                if missing
                else "Один или несколько структурированных фактов не подтверждены."
            ),
            explanation_accepted=False,
            field_errors=field_errors,
        )
    return MissionGrade(
        status=MissionGradeStatus.solved,
        reason="Артефакт и структурированный разбор подтверждены.",
        explanation_accepted=False,
    )
