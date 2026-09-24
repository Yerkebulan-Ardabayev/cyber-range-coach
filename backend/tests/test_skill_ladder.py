"""Skill ladder, spec.md 11.3 Д and AC-11-5."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from cyber_range_coach.models import Evidence, LabRun, LearningSession, ReviewItem, SkillState
from cyber_range_coach.services.curriculum import Curriculum
from cyber_range_coach.services.grader import command_by_meaning

STEP1, STEP2, STEP3 = "linux-navigation-pwd", "linux-navigation-home", "linux-navigation-logs"
OUTPUT = {STEP1: "/home/student\n", STEP2: "/home/student\n", STEP3: "/var/log\n"}


def _run(client, lesson_id: str, *, help_used: bool = False, lines: list[str] | None = None) -> int:
    lesson = client.app.state.curriculum.lesson(lesson_id)
    lines = lines or [lesson.command]
    with client.app.state.db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson_id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson_id,
            skill_id=lesson.skill_id,
            prediction="Ожидаю адрес папки",
            transcript="".join(f"student$ {line}\n" for line in lines) + OUTPUT[lesson_id],
            terminal_inputs=lines,
            input_integrity="verified",
            help_used=help_used,
            help_opened_at=datetime.now(UTC) if help_used else None,
        )
        session.add(run)
        session.commit()
        return run.id


def _pass(client, lesson_id: str, *, help_used: bool = False) -> dict[str, object]:
    run_id = _run(client, lesson_id, help_used=help_used)
    assert client.post(f"/api/v2/lab-runs/{run_id}/grade").json()["status"] == "passed"
    assert (
        client.post(
            f"/api/v2/lab-runs/{run_id}/explanation",
            json={"text": "Адрес подтверждён выводом pwd."},
        ).status_code
        == 200
    )
    assert client.post("/api/v2/tutor-feedback", json={"run_id": run_id}).status_code == 200
    final = client.post(
        f"/api/v2/lab-runs/{run_id}/finalize",
        json={
            "corrected_conclusion": "Переход удался, вывод показал нужный адрес.",
            "limitation": "Это только текущая папка.",
            "next_test": "Повторить из другой папки.",
        },
    )
    assert final.status_code == 200, final.json()
    return dict(final.json())


def _start(client, lesson_id: str):
    session = client.post(
        "/api/v2/sessions", json={"duration_minutes": 15, "lesson_ids": [lesson_id]}
    )
    return client.post(
        "/api/v2/lab-runs",
        json={
            "session_id": session.json()["id"],
            "lesson_id": lesson_id,
            "prediction": "Жду адрес",
        },
    )


def _age_help(client, days: int = 2) -> None:
    """Move opened help into the past, as if the learner came back later."""
    with client.app.state.db.session_factory() as session:
        for run in session.query(LabRun).filter(LabRun.help_used.is_(True)):
            run.help_opened_at = datetime.now(UTC) - timedelta(days=days)
        session.commit()


def _stage(client, skill_id: str) -> str:
    with client.app.state.db.session_factory() as session:
        state = session.get(SkillState, skill_id)
        return state.stage if state else "none"


def test_every_linux_skill_has_three_steps(client) -> None:
    curriculum = client.app.state.curriculum
    for skill in (
        "linux-navigation",
        "linux-files",
        "linux-reading",
        "linux-text-processing",
        "linux-redirection",
        "linux-search",
        "linux-permissions",
        "linux-identity",
    ):
        steps = sorted(
            item.ladder_step for item in curriculum.lessons.values() if item.skill_id == skill
        )
        assert steps == [1, 2, 3], skill


def test_step_two_is_locked_until_step_one_passes(client) -> None:
    locked = _start(client, STEP2)
    assert locked.status_code == 409
    assert locked.json()["code"] == "ladder_step_locked"


def test_step_command_is_hidden_until_help_and_help_is_recorded(client) -> None:
    lesson = client.get(f"/api/v2/lessons/{STEP2}").json()
    assert lesson["command"] == "" and lesson["grader"] is None and lesson["command_hidden"] is True
    listed = next(
        item for item in client.get("/api/v2/curriculum").json()["lessons"] if item["id"] == STEP2
    )
    assert listed["command"] == "" and listed["accepted_commands"] == []
    assert client.get(f"/api/v2/lessons/{STEP1}").json()["command"] == "pwd"
    run_id = _run(client, STEP2)
    assert client.get(f"/api/v2/lab-runs/{run_id}/lesson").json()["rendered_command"] == ""
    opened = client.post(f"/api/v2/lab-runs/{run_id}/reveal-command").json()
    assert opened["rendered_command"] == "cd ~ && pwd"
    assert client.get(f"/api/v2/lab-runs/{run_id}").json()["help_used"] is True


def test_steps_raise_the_skill_only_when_done_without_help(client) -> None:
    assert _pass(client, STEP1)["evidence_stage"] == "guided"
    assisted = _pass(client, STEP2, help_used=True)
    assert assisted["evidence_stage"] == "guided"
    with client.app.state.db.session_factory() as session:
        decisions = [item.grader_decision for item in session.query(Evidence).all()]
        review = session.query(ReviewItem).filter(ReviewItem.lesson_id == STEP2).one()
        due_at = review.due_at if review.due_at.tzinfo else review.due_at.replace(tzinfo=UTC)
    assert decisions == ["passed", "passed_with_help"]
    assert due_at < datetime.now(UTC) + timedelta(days=1, hours=1)
    assert _start(client, STEP3).json()["code"] == "ladder_step_locked"
    # Re-typing the command just seen is still help; the clean try is tomorrow.
    assert _pass(client, STEP2)["evidence_stage"] == "guided"
    _age_help(client)
    assert _pass(client, STEP2)["evidence_stage"] == "independent"
    assert _pass(client, STEP3)["evidence_stage"] == "transfer"
    assert _stage(client, "linux-navigation") == "transfer"


def test_plan_offers_only_open_steps(client) -> None:
    offered = {
        item["id"]
        for duration in (15, 45, 90)
        for item in client.post(
            "/api/v2/session-plans", json={"duration_minutes": duration}
        ).json()["lessons"]
    }
    ladder = client.app.state.curriculum
    assert not any(ladder.lesson(lesson_id).ladder_step > 1 for lesson_id in offered)


def test_ladder_with_a_gap_is_rejected(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "curriculum" / "fundamentals.yaml"
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    document["lessons"] = [item for item in document["lessons"] if item["id"] != STEP2]
    (tmp_path / "fundamentals.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="ladder steps"):
        Curriculum(tmp_path)


def test_help_in_another_session_still_counts(client) -> None:
    _pass(client, STEP1)
    peeked = _run(client, STEP2)
    assert client.post(f"/api/v2/lab-runs/{peeked}/reveal-command").status_code == 200
    assert client.post(f"/api/v2/lab-runs/{peeked}/stop").status_code == 200
    assert _pass(client, STEP2)["evidence_stage"] == "guided"
    with client.app.state.db.session_factory() as session:
        decisions = [item.grader_decision for item in session.query(Evidence).all()]
    assert decisions == ["passed", "passed_with_help"]
    _age_help(client)
    assert _pass(client, STEP2)["evidence_stage"] == "independent"


def test_step_is_graded_by_meaning_not_spelling(client) -> None:
    for lines in (["cd; pwd"], ["cd", "pwd"], ["cd /home/student && pwd"]):
        run_id = _run(client, STEP2, lines=lines)
        assert client.post(f"/api/v2/lab-runs/{run_id}/grade").json()["status"] == "passed", lines
        client.post(f"/api/v2/lab-runs/{run_id}/stop")
    faked = _run(client, STEP2, lines=["cd; echo /home/student # pwd"])
    assert client.post(f"/api/v2/lab-runs/{faked}/grade").json()["status"] == "needs_evidence"


def test_transfer_step_has_no_help_button(client) -> None:
    run_id = _run(client, STEP3)
    refused = client.post(f"/api/v2/lab-runs/{run_id}/reveal-command")
    assert refused.status_code == 409
    assert refused.json()["code"] == "no_help_on_transfer"
    assert client.get(f"/api/v2/lab-runs/{run_id}").json()["help_used"] is False
    assert client.get(f"/api/v2/lab-runs/{run_id}/lesson").json()["rendered_command"] == ""


def test_comment_or_extra_program_can_not_fake_a_step(client) -> None:
    fakes = {
        STEP2: ["cd /tmp; ls -d ~ # pwd", "cd . && pwd"],
        STEP3: ["cd /tmp; ls -d /var/log # pwd"],
    }
    for lesson_id, variants in fakes.items():
        for line in variants:
            run_id = _run(client, lesson_id, lines=[line])
            graded = client.post(f"/api/v2/lab-runs/{run_id}/grade").json()
            assert graded["status"] == "needs_evidence", line
            client.post(f"/api/v2/lab-runs/{run_id}/stop")


def test_words_in_a_shell_comment_do_not_count(client) -> None:
    note = client.app.state.curriculum.lesson("text-redirection-note")
    faked = "printf 'alpha\\nbeta\\n' > ~/crc-note.txt && cat ~/crc-note.txt # >> crc-note.txt"
    real = "echo alpha > ~/crc-note.txt && echo beta >> ~/crc-note.txt && cat ~/crc-note.txt"
    assert not command_by_meaning(note, [faked])
    assert command_by_meaning(note, [real])


def test_help_opened_in_an_old_run_still_counts(client) -> None:
    _pass(client, STEP1)
    run_id = _run(client, STEP2)
    with client.app.state.db.session_factory() as session:
        run = session.get(LabRun, run_id)
        run.created_at = datetime.now(UTC) - timedelta(days=2)
        session.commit()
    assert client.post(f"/api/v2/lab-runs/{run_id}/reveal-command").status_code == 200
    assert client.post(f"/api/v2/lab-runs/{run_id}/grade").json()["status"] == "passed"
    client.post(f"/api/v2/lab-runs/{run_id}/explanation", json={"text": "Адрес подтверждён."})
    client.post("/api/v2/tutor-feedback", json={"run_id": run_id})
    final = client.post(
        f"/api/v2/lab-runs/{run_id}/finalize",
        json={
            "corrected_conclusion": "Переход удался, вывод показал адрес.",
            "limitation": "Это только текущая папка.",
            "next_test": "Повторить из другой папки.",
        },
    )
    assert final.json()["evidence_stage"] == "guided"


def test_empty_append_and_wrong_order_do_not_count(client) -> None:
    note = client.app.state.curriculum.lesson("text-redirection-note")
    home = client.app.state.curriculum.lesson(STEP2)
    empty_append = (
        "printf 'alpha\\nbeta\\n' > ~/crc-note.txt; printf '' >> ~/crc-note.txt; cat ~/crc-note.txt"
    )
    assert not command_by_meaning(note, [empty_append])
    assert not command_by_meaning(home, ["pwd; cd ~"])
    assert command_by_meaning(home, ["cd", "pwd"])
