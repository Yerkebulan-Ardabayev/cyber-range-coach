"""Run every skill-ladder command in the reference Linux and grade it (AC-11-6).

For each skill with steps 2 and 3, every accepted command must pass the real
lesson grader on its real output, and every wrong command from
curriculum/output-fixtures/ladder.yaml must not. Steps 2 and 3 must not
reveal their command in the text shown before the attempt.

    uv run python tools/validate_ladder.py
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cyber_range_coach.models import Base, LabRun, LearningSession
from cyber_range_coach.services.curriculum import Curriculum, Lesson
from cyber_range_coach.services.grader import grade_run

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "cyber-range-coach-reference:24.04"
DOCKER = shutil.which("docker") or "/opt/homebrew/bin/docker"
MARK = "@@CRC-LADDER@@"
# One terminal line, or several lines typed one after another in one attempt.
Answer = str | list[str]
BOOTSTRAP = """set -eu
userdel -r ubuntu >/dev/null 2>&1 || true
useradd -m -u 1000 -s /bin/bash -G sudo student
# A WSL home is not a fresh /etc/skel copy.
install -d -o student -g student /home/student/.cache /home/student/.ssh
install -o student -g student -m 644 /dev/null /home/student/.sudo_as_admin_successful
"""


def ladder_lessons(curriculum: Curriculum) -> list[Lesson]:
    return [
        lesson for lesson in curriculum.ordered_lessons() if curriculum.has_ladder(lesson.skill_id)
    ]


def run_all(answers: list[Answer]) -> list[str]:
    """Run each command as student from the home directory, one fresh shell each."""
    script = BOOTSTRAP
    commands = [answer if isinstance(answer, str) else "\n".join(answer) for answer in answers]
    for index, command in enumerate(commands):
        encoded = base64.b64encode(command.encode()).decode()
        script += f"echo '{MARK}{index}'\n"
        script += f'su - student -c "bash -c \\"\\$(echo {encoded} | base64 -d)\\"" 2>&1 || true\n'
    completed = subprocess.run(
        [
            DOCKER,
            "run",
            "--rm",
            "-i",
            "--hostname",
            "training-vm",
            "--entrypoint",
            "bash",
            IMAGE,
            "-s",
        ],
        input=script,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    outputs = [""] * len(commands)
    current = -1
    for line in completed.stdout.splitlines(True):
        if line.startswith(MARK):
            current = int(line[len(MARK) :])
            continue
        if current >= 0:
            outputs[current] += line
    return outputs


def grade(session: Session, lesson: Lesson, command: Answer, output: str) -> tuple[str, bool]:
    """Return the grader status and whether the command check itself passed."""
    lines = [command] if isinstance(command, str) else list(command)
    learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
    session.add(learning)
    session.flush()
    run = LabRun(
        session_id=learning.id,
        lesson_id=lesson.id,
        skill_id=lesson.skill_id,
        prediction="validator",
        transcript="".join(f"student@training-vm:~$ {line}\n" for line in lines) + output,
        terminal_inputs=lines,
        input_integrity="verified",
    )
    session.add(run)
    session.flush()
    report = grade_run(session, run, lesson)
    run.status = "completed"  # only one active run is allowed at a time
    session.flush()
    command_ok = any(check["kind"] == "command" and check["passed"] for check in report.checks)
    return report.status, command_ok


def visible_text(lesson: Lesson) -> str:
    parts = [lesson.title, lesson.summary, lesson.worked_example, lesson.prediction_question]
    parts += [lesson.term.definition, lesson.explanation_prompt, lesson.review_question]
    if lesson.simple_theory is not None:
        theory = lesson.simple_theory
        parts += [theory.analogy, *theory.what_it_does, theory.picture, theory.check_question]
        parts += [theory.check_answer]
    return "\n".join(parts)


def main() -> int:
    curriculum = Curriculum(ROOT / "curriculum")
    wrong = yaml.safe_load((ROOT / "curriculum" / "output-fixtures" / "ladder.yaml").read_text())
    wrong_commands: dict[str, list[Answer]] = wrong["wrong_commands"]
    right_commands: dict[str, list[Answer]] = wrong.get("right_commands", {})
    lessons = ladder_lessons(curriculum)
    errors: list[str] = []
    cases: list[tuple[Lesson, Answer, bool]] = []
    for lesson in lessons:
        cases += [(lesson, command, True) for command in lesson.commands()]
        cases += [(lesson, command, True) for command in right_commands.get(lesson.id, [])]
        if not wrong_commands.get(lesson.id):
            errors.append(f"{lesson.id}: no wrong commands to reject")
        cases += [(lesson, command, False) for command in wrong_commands.get(lesson.id, [])]
        if lesson.ladder_step > 1:
            shown = visible_text(lesson)
            for command in lesson.commands():
                if command in shown:
                    errors.append(f"{lesson.id}: shown text reveals the command {command!r}")
    outputs = run_all([command for _lesson, command, _ok in cases])
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    rejected_by_output: set[str] = set()
    with Session(engine) as session:
        for (lesson, answer, should_pass), output in zip(cases, outputs, strict=True):
            status, command_ok = grade(session, lesson, answer, output)
            if not should_pass and command_ok and status != "passed":
                rejected_by_output.add(lesson.id)
            if should_pass and status != "passed":
                errors.append(
                    f"{lesson.id}: accepted {answer!r} got {status}: {output.strip()[:120]!r}"
                )
            if not should_pass and status == "passed":
                errors.append(f"{lesson.id}: wrong {answer!r} passed")
    for lesson in lessons:
        if lesson.ladder_step > 1 and lesson.id not in rejected_by_output:
            errors.append(f"{lesson.id}: no wrong answer is rejected by its output alone")
    skills = {lesson.skill_id for lesson in lessons}
    for message in errors:
        print(message)
    print(f"skills with ladder: {len(skills)}, lessons: {len(lessons)}, cases: {len(cases)}")
    print("LADDER VALIDATION " + ("FAILED" if errors else "PASSED"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
