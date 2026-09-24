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
from ..models import Evidence, LabRun, ReviewItem, SkillState
from ..schemas import LessonSummary, SessionPlanResponse
from .simple_theory import SimpleTheory


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
    stage: Literal["introduced", "guided", "independent", "transfer"]
    # Skill ladder (spec 11.3 Д): 1 guided, 2 on your own, 3 transfer.
    ladder_step: Literal[1, 2, 3] = 1
    target_tags: list[str]
    requires_target: bool
    term: Term
    simple_theory: SimpleTheory | None = None
    worked_example: str
    prediction_question: str
    command: str
    accepted_commands: list[str] = Field(default_factory=list)
    # Steps 2-3 are graded by meaning: the run's lines are tokenized like a
    # shell (quotes removed, comments dropped), every pattern must match the
    # tokens, every program must be in command_tools, and the output decides.
    command_patterns: list[str] = Field(default_factory=list)
    command_tools: list[str] = Field(default_factory=list)
    command_explanation: list[str]
    grader: GraderSpec
    explanation_prompt: str
    review_question: str

    def commands(self) -> list[str]:
        return [self.command, *self.accepted_commands]

    def public_dump(self, reveal_command: bool = False) -> dict[str, object]:
        """Steps 2 and 3 are done without the answer: hide command and grader."""
        data = self.model_dump()
        if self.ladder_step > 1 and not reveal_command:
            data["command"] = ""
            data["accepted_commands"] = []
            data["command_patterns"] = []
            data["command_tools"] = []
            data["command_explanation"] = []
            data["grader"] = None
        data["command_hidden"] = self.ladder_step > 1 and not reveal_command
        return data

    def summary_model(self) -> LessonSummary:
        return LessonSummary(
            id=self.id,
            title=self.title,
            summary=self.summary,
            estimated_minutes=self.estimated_minutes,
            skill_id=self.skill_id,
            stage=self.stage,
            target_tags=self.target_tags,
            ladder_step=self.ladder_step,
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


def step_cleanly_passed(session: Session, lesson_id: str) -> bool:
    """A ladder step opens only after the previous one was passed without help."""
    return (
        session.scalar(
            select(Evidence.id)
            .join(LabRun, LabRun.id == Evidence.run_id)
            .where(LabRun.lesson_id == lesson_id, Evidence.grader_decision == "passed")
            .limit(1)
        )
        is not None
    )


def _check_ladders(lessons: dict[str, Lesson]) -> None:
    steps: dict[str, list[int]] = {}
    for lesson in lessons.values():
        steps.setdefault(lesson.skill_id, []).append(lesson.ladder_step)
    for lesson in lessons.values():
        if lesson.ladder_step > 1 and not (lesson.command_patterns and lesson.command_tools):
            raise ValueError(f"ladder step {lesson.id} needs command_patterns and command_tools")
    for skill_id, values in steps.items():
        if sorted(values) != list(range(1, len(values) + 1)) or len(values) > 3:
            raise ValueError(f"skill {skill_id} ladder steps must be 1..n without gaps: {sorted(values)}")


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
        _check_ladders(lessons)
        self.tracks = tracks
        self.lessons = lessons

    def lesson(self, lesson_id: str) -> Lesson:
        lesson = self.lessons.get(lesson_id)
        if lesson is None:
            raise AppError(404, "lesson_not_found", "Урок не найден.", {"lesson_id": lesson_id})
        return lesson

    def previous_step(self, lesson: Lesson) -> Lesson | None:
        if lesson.ladder_step == 1:
            return None
        return next(
            item
            for item in self.lessons.values()
            if item.skill_id == lesson.skill_id and item.ladder_step == lesson.ladder_step - 1
        )

    def step_open(self, session: Session, lesson: Lesson) -> bool:
        previous = self.previous_step(lesson)
        return previous is None or step_cleanly_passed(session, previous.id)

    def has_ladder(self, skill_id: str) -> bool:
        return any(item.skill_id == skill_id and item.ladder_step > 1 for item in self.lessons.values())

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
            and self.step_open(session, lesson)
        ]
        options: list[tuple[tuple[int, int, int, int], tuple[Lesson, ...]]] = []
        for size in range(1, selection_limit + 1):
            for option in combinations(candidates, size):
                total = sum(lesson.estimated_minutes for lesson in option)
                if total > lesson_budget:
                    continue
                score = (
                    sum(lesson.id in due_ids for lesson in option),
                    total,
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
