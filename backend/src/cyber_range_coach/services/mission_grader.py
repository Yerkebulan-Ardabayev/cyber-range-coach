from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from .recall_grader import grade_observation


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


class MissionGradingContract(BaseModel):
    artifact: MissionArtifactContract
    explanation: MissionExplanationContract


class MissionGrade(BaseModel):
    status: MissionGradeStatus
    reason: str
    explanation_accepted: bool


def grade_mission(
    artifact: str | None,
    explanation: str | None,
    contract: MissionGradingContract,
) -> MissionGrade:
    """Grade a declared result only. The learner input is never executed."""
    declared_artifact = (artifact or "").strip()
    declared_explanation = explanation or ""
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
                explanation_accepted=grade_observation(
                    declared_explanation,
                    contract.explanation.expected_concepts,
                ),
            )
        return MissionGrade(
            status=MissionGradeStatus.wrong_artifact,
            reason="Заявленный артефакт не подтверждается подготовленными данными.",
            explanation_accepted=False,
        )
    explanation_accepted = grade_observation(
        declared_explanation,
        contract.explanation.expected_concepts,
    )
    if not explanation_accepted:
        return MissionGrade(
            status=MissionGradeStatus.unexplained,
            reason="Артефакт найден, но связь с задачей не объяснена.",
            explanation_accepted=False,
        )
    return MissionGrade(
        status=MissionGradeStatus.solved,
        reason="Финальный артефакт и объяснение подтверждены.",
        explanation_accepted=True,
    )
