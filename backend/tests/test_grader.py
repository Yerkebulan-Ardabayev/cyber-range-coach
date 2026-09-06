from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from cyber_range_coach.models import Evidence, LabRun, LearningSession, ReviewItem
from cyber_range_coach.services.grader import grade_run, record_evidence


def add_session(db_session):
    learning = LearningSession(duration_minutes=45, lesson_ids=["http-response"])
    db_session.add(learning)
    db_session.flush()
    return learning


def test_http_failure_never_becomes_http_response(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("http-response")
    with db.session_factory() as session:
        learning = add_session(session)
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Ожидаю HTTP status",
            transcript="curl: (7) Failed to connect: Connection refused\n",
            terminal_inputs=["printf 'HTTP/1.1 200 OK\\nContent-Type: text/plain\\n'"],
            input_integrity="verified",
        )
        session.add(run)
        session.commit()
        result = grade_run(
            session,
            run,
            lesson,
            {
                "target_host": "192.168.1.10",
                "target_port": "47001",
                "target_url": "http://192.168.1.10:47001/",
            },
            '{"check":"http","reachable":false}',
        )
        assert result.status == "needs_evidence"
        assert result.evidence_stage is None
        assert "HTTP" not in lesson.grader.fact_template or result.status != "passed"


def test_transfer_requires_distinct_target_fingerprint(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("http-response")
    with db.session_factory() as session:
        learning = add_session(session)
        stages = []
        for fingerprint in ("same", "same", "different"):
            run = LabRun(
                session_id=learning.id,
                lesson_id=lesson.id,
                skill_id=lesson.skill_id,
                target_fingerprint=fingerprint,
                status="completed",
                prediction="Ожидаю реальный HTTP response",
            )
            session.add(run)
            session.flush()
            stages.append(record_evidence(session, run, lesson))
            session.commit()
        assert stages[0] == "guided"
        assert stages[1] == "independent"
        assert stages[2] == "transfer"


def test_linux_only_skill_stops_at_independent(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("text-pipes-grep")
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=45, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        stages = []
        for _ in range(3):
            run = LabRun(
                session_id=learning.id,
                lesson_id=lesson.id,
                skill_id=lesson.skill_id,
                status="completed",
                prediction="Ожидаю отфильтрованную строку",
            )
            session.add(run)
            session.flush()
            stages.append(record_evidence(session, run, lesson))
            session.commit()
        assert stages == ["guided", "independent", "independent"]


def test_correct_pipe_output_ignores_command_text_and_passes(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("text-pipes-grep")
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Останется одна строка",
            transcript=f"student$ {lesson.command}\nLISTEN 8080\n",
            terminal_inputs=[lesson.command],
            input_integrity="verified",
        )
        session.add(run)
        session.flush()
        result = grade_run(session, run, lesson)
        assert result.status == "passed"
        assert result.evidence_stage is None


def test_echoed_approved_command_is_not_observed_output(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("authentication-boundary")
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Ожидаю две записи",
            transcript=f"student$ {lesson.command}\n",
            terminal_inputs=[lesson.command],
            input_integrity="verified",
        )
        session.add(run)
        session.flush()
        result = grade_run(session, run, lesson)
        assert result.status == "needs_evidence"


def test_input_not_verifiable_is_technical_limit_not_a_failed_command(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("text-pipes-grep")
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Останется одна строка",
            transcript=f"student$ {lesson.command}\nLISTEN 8080\n",
            terminal_inputs=[lesson.command],
            input_integrity="unverified",
            input_integrity_reason="tab_completion",
        )
        session.add(run)
        session.flush()
        result = grade_run(session, run, lesson)
        assert result.status == "needs_evidence"
        check = next(item for item in result.checks if item["kind"] == "input_integrity")
        assert check["passed"] is False
        assert check["reason"] == "tab_completion"


def test_follow_up_fake_command_cannot_supply_observation(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("text-pipes-grep")
    fake = "printf 'LISTEN 8080\\n'"
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Ожидаю одну строку",
            transcript=f"student$ {lesson.command}\nfailed\nstudent$ {fake}\nLISTEN 8080\n",
            terminal_inputs=[lesson.command, fake],
            input_integrity="verified",
        )
        session.add(run)
        session.flush()
        result = grade_run(session, run, lesson)
        assert result.status == "needs_evidence"
        assert any(
            check["kind"] == "responses" and check["passed"] is False for check in result.checks
        )


def test_earlier_fake_command_cannot_supply_observation(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("text-pipes-grep")
    fake = "printf 'LISTEN 8080\\n'"
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Ожидаю одну строку",
            transcript=f"student$ {fake}\nLISTEN 8080\nstudent$ {lesson.command}\nfailed\n",
            terminal_inputs=[fake, lesson.command],
            input_integrity="verified",
        )
        session.add(run)
        session.flush()
        result = grade_run(session, run, lesson)
        assert result.status == "needs_evidence"
        assert any(
            check["kind"] == "attempt_boundary" and check["passed"] is False
            for check in result.checks
        )


def test_gateway_offsets_exclude_spoofed_approved_echo_before_real_command(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("text-pipes-grep")
    fake = f"printf 'student$ {lesson.command}\\nLISTEN 8080\\n'"
    fake_chunk = f"student$ {fake}\nstudent$ {lesson.command}\nLISTEN 8080\n"
    real_chunk = f"student$ {lesson.command}\nfailed\n"
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Ожидаю одну строку",
            transcript=fake_chunk + real_chunk,
            terminal_inputs=[fake, lesson.command],
            terminal_input_offsets=[0, len(fake_chunk)],
            input_integrity="verified",
        )
        session.add(run)
        session.flush()
        result = grade_run(session, run, lesson)
        assert result.status == "needs_evidence"


def test_type_ahead_output_from_previous_process_cannot_pass(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("text-pipes-grep")
    payload = base64.b64encode(
        f"student$ {lesson.command}\nLISTEN 8080\n".encode()
    ).decode()
    fake = f"sleep 1; printf {payload} | base64 -d"
    prefix = f"student$ {fake}\n"
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Ожидаю одну строку",
            transcript=(
                prefix
                + f"{lesson.command}\nstudent$ {lesson.command}\nLISTEN 8080\nfailed\n"
            ),
            terminal_inputs=[fake, lesson.command],
            terminal_input_offsets=[0, len(prefix)],
            input_integrity="verified",
        )
        session.add(run)
        session.flush()
        result = grade_run(session, run, lesson)
        assert result.status == "needs_evidence"
        assert any(
            check["kind"] == "attempt_boundary" and check["passed"] is False
            for check in result.checks
        )


def test_evidence_report_keeps_six_interactive_answers(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("evidence-report")
    answers = ["local lab", "curl", "HTTP 200", "service replied", "one path", "check headers"]
    output = "\n".join(
        (
            "SCOPE: local lab",
            "STEP: curl",
            "OBSERVATION: HTTP 200",
            "CONCLUSION: service replied",
            "LIMITATION: one path",
            "NEXT TEST: check headers",
        )
    )
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Ожидаю шесть полей",
            transcript=f"student$ {lesson.command}\n{output}\n",
            terminal_inputs=[lesson.command, *answers],
            terminal_input_kinds=["shell_command", *("program_response" for _ in answers)],
            input_integrity="verified",
        )
        session.add(run)
        session.flush()
        result = grade_run(session, run, lesson)
        assert result.status == "passed"


def test_evidence_requires_explanation_tutor_and_final_debrief(client) -> None:
    db = client.app.state.db
    lesson = client.app.state.curriculum.lesson("text-pipes-grep")
    with db.session_factory() as session:
        learning = LearningSession(duration_minutes=15, lesson_ids=[lesson.id])
        session.add(learning)
        session.flush()
        run = LabRun(
            session_id=learning.id,
            lesson_id=lesson.id,
            skill_id=lesson.skill_id,
            prediction="Останется одна строка",
            transcript=f"student$ {lesson.command}\nLISTEN 8080\n",
            terminal_inputs=[lesson.command],
            input_integrity="verified",
        )
        session.add(run)
        session.add(
            ReviewItem(
                skill_id=lesson.skill_id,
                lesson_id=lesson.id,
                due_at=datetime.now(UTC) - timedelta(days=1),
                reason="Проверить закрытие due review.",
            )
        )
        session.commit()
        run_id = run.id
        session_id = learning.id

    observed = client.post(f"/api/v2/lab-runs/{run_id}/grade")
    assert observed.status_code == 200
    assert observed.json()["status"] == "passed"
    with db.session_factory() as session:
        assert session.query(Evidence).count() == 0

    explanation = client.post(
        f"/api/v2/lab-runs/{run_id}/explanation",
        json={"text": "Pipe передал stdout, grep оставил только строку LISTEN."},
    )
    assert explanation.status_code == 200
    tutor = client.post("/api/v2/tutor-feedback", json={"run_id": run_id})
    assert tutor.status_code == 200
    reloaded = client.get(f"/api/v2/lab-runs/{run_id}")
    assert reloaded.status_code == 200
    assert reloaded.json()["tutor_question"] == tutor.json()["question"]
    assert reloaded.json()["tutor_explanation"] == tutor.json()["explanation"]
    unchanged = client.post(
        f"/api/v2/lab-runs/{run_id}/finalize",
        json={
            "corrected_conclusion": "Pipe передал stdout, grep оставил только строку LISTEN.",
            "limitation": "Это контролируемый набор данных.",
            "next_test": "Повторить фильтр на другом файле.",
        },
    )
    assert unchanged.status_code == 409
    assert unchanged.json()["code"] == "correction_unchanged"
    final = client.post(
        f"/api/v2/lab-runs/{run_id}/finalize",
        json={
            "corrected_conclusion": "После фильтра осталась только строка LISTEN.",
            "limitation": "Это контролируемый набор данных.",
            "next_test": "Повторить фильтр на другом файле.",
        },
    )
    assert final.status_code == 200
    assert final.json()["evidence_stage"] == "guided"
    with db.session_factory() as session:
        assert session.query(Evidence).count() == 1
        reviews = session.query(ReviewItem).order_by(ReviewItem.id).all()
        assert len(reviews) == 2
        assert reviews[0].completed_at is not None
        assert reviews[1].completed_at is None
        stored_session = session.get(LearningSession, session_id)
        assert stored_session is not None
        assert stored_session.status == "completed"
        assert stored_session.completed_at is not None
