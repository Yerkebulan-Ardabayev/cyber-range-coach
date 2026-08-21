from __future__ import annotations

from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models import ReviewItem, SkillState
from ..schemas import LessonSummary, SessionPlanResponse


class Term(BaseModel):
    name: str
    definition: str


class GraderSpec(BaseModel):
    source: Literal["transcript", "explanation", "probe"]
    probe: Literal["relay", "nmap", "http"] | None = None
    response_count: int = Field(default=0, ge=0, le=20)
    required_patterns: list[str] = Field(default_factory=list)
    forbidden_patterns: list[str] = Field(default_factory=list)
    fact_template: str


class Lesson(BaseModel):
    id: str
    order: int
    title: str
    summary: str
    estimated_minutes: int
    skill_id: str
    stage: Literal["introduced", "guided", "independent"]
    target_tags: list[str]
    requires_target: bool
    term: Term
    worked_example: str
    prediction_question: str
    command: str
    command_explanation: list[str]
    grader: GraderSpec
    explanation_prompt: str
    review_question: str

    def summary_model(self) -> LessonSummary:
        return LessonSummary(
            id=self.id,
            title=self.title,
            summary=self.summary,
            estimated_minutes=self.estimated_minutes,
            skill_id=self.skill_id,
            stage=self.stage,
            target_tags=self.target_tags,
        )


class Track(BaseModel):
    id: str
    title: str
    summary: str
    role: str
    version: int


class CurriculumDocument(BaseModel):
    track: Track
    lessons: list[Lesson]


class Curriculum:
    def __init__(self, directory: Path):
        self.directory = directory
        self.tracks: dict[str, Track] = {}
        self.lessons: dict[str, Lesson] = {}
        self.reload()

    def reload(self) -> None:
        tracks: dict[str, Track] = {}
        lessons: dict[str, Lesson] = {}
        for path in sorted(self.directory.glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            document = CurriculumDocument.model_validate(payload)
            if document.track.id in tracks:
                raise ValueError(f"duplicate track id: {document.track.id}")
            tracks[document.track.id] = document.track
            for lesson in document.lessons:
                if lesson.id in lessons:
                    raise ValueError(f"duplicate lesson id: {lesson.id}")
                lessons[lesson.id] = lesson
        if not lessons:
            raise ValueError(f"no curriculum lessons found in {self.directory}")
        self.tracks = tracks
        self.lessons = lessons

    def lesson(self, lesson_id: str) -> Lesson:
        lesson = self.lessons.get(lesson_id)
        if lesson is None:
            raise AppError(404, "lesson_not_found", "Урок не найден.", {"lesson_id": lesson_id})
        return lesson

    def ordered_lessons(self) -> list[Lesson]:
        return sorted(self.lessons.values(), key=lambda item: item.order)

    def plan(self, session: Session, duration_minutes: int) -> SessionPlanResponse:
        counts = {15: 1, 45: 3, 90: 5}
        if duration_minutes not in counts:
            raise AppError(422, "invalid_duration", "Доступны сессии 15, 45 или 90 минут.")
        now = datetime.now(UTC)
        due = session.scalars(
            select(ReviewItem)
            .where(ReviewItem.completed_at.is_(None), ReviewItem.due_at <= now)
            .order_by(ReviewItem.due_at)
        ).all()
        reserve_report = duration_minutes == 90 and "evidence-report" in self.lessons
        selection_limit = counts[duration_minutes] - (1 if reserve_report else 0)
        report_minutes = self.lessons["evidence-report"].estimated_minutes if reserve_report else 0
        lesson_budget = duration_minutes - report_minutes
        states = {state.skill_id: state for state in session.scalars(select(SkillState)).all()}
        due_ids = {item.lesson_id for item in due}
        candidates = [
            lesson
            for lesson in self.ordered_lessons()
            if not (reserve_report and lesson.id == "evidence-report")
        ]
        options: list[tuple[tuple[int, int, int, int], tuple[Lesson, ...]]] = []
        for size in range(1, selection_limit + 1):
            for option in combinations(candidates, size):
                total = sum(lesson.estimated_minutes for lesson in option)
                if total > lesson_budget:
                    continue
                score = (
                    total,
                    sum(lesson.id in due_ids for lesson in option),
                    sum(lesson.skill_id not in states for lesson in option),
                    -sum(lesson.order for lesson in option),
                )
                options.append((score, option))
        if not options:
            raise AppError(409, "session_plan_empty", "Не удалось собрать маршрут в заданное время.")
        selected = max(options, key=lambda item: item[0])[1]
        lesson_ids = [lesson.id for lesson in selected]
        rationale = [
            (
                f"Повторение просрочено: {lesson.title}."
                if lesson.id in due_ids
                else f"Рекомендуемый следующий навык: {lesson.title}."
            )
            for lesson in selected
        ]
        if reserve_report:
            lesson_ids.append("evidence-report")
            rationale.append("90 минут завершаются доказательным отчётом.")
        return SessionPlanResponse(
            duration_minutes=duration_minutes,
            lessons=[self.lessons[item].summary_model() for item in lesson_ids],
            rationale=rationale,
        )
