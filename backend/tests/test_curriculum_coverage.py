from __future__ import annotations

from cyber_range_coach.services.curriculum import Curriculum


def test_foundation_course_covers_declared_core_tools(settings) -> None:
    curriculum = Curriculum(settings.curriculum_dir)
    lessons = curriculum.ordered_lessons()
    combined_commands = "\n".join(lesson.command for lesson in lessons)
    expected_tools = {
        "pwd",
        "ls",
        "cd",
        "cat",
        "less",
        "grep",
        "find",
        "stat",
        "id",
        "install",
        "getent",
        "ip",
        "nc",
        "nmap",
        "curl",
        "awk",
    }
    assert len(lessons) >= 19
    for tool in expected_tools:
        assert tool in combined_commands
    assert ">" in combined_commands
    assert ">>" in combined_commands
    assert any(lesson.skill_id == "authentication-boundary" for lesson in lessons)
    assert any(lesson.skill_id == "access-control" for lesson in lessons)
    assert any(lesson.skill_id == "blue-auth-triage" for lesson in lessons)


def test_session_plans_fit_their_timebox_and_ninety_minutes_end_with_report(client) -> None:
    with client.app.state.db.session_factory() as session:
        plans = [client.app.state.curriculum.plan(session, minutes) for minutes in (15, 45, 90)]
    for minutes, plan in zip((15, 45, 90), plans, strict=True):
        assert sum(lesson.estimated_minutes for lesson in plan.lessons) == minutes
        assert plan.lessons
    assert plans[-1].lessons[-1].id == "evidence-report"


def test_http_lessons_and_blue_mirror_have_reproducible_contracts(settings) -> None:
    curriculum = Curriculum(settings.curriculum_dir)
    request = curriculum.lesson("http-request-structure")
    response = curriculum.lesson("http-response")
    blue = curriculum.lesson("blue-auth-log-triage")
    assert "--http1.1" in request.command
    assert any(
        '"request_protocol": "HTTP/1\\.1"' in item for item in request.grader.required_patterns
    )
    assert "--http1.1" in response.command
    assert '"response_protocol": "HTTP/1\\.1"' in response.grader.required_patterns
    assert "event=auth" in blue.command
    assert "event=access" in blue.command
    assert '> "$log"' in blue.command


def test_foundation_examples_do_not_present_synthetic_network_claims_as_facts(settings) -> None:
    curriculum = Curriculum(settings.curriculum_dir)
    scope = curriculum.lesson("scope-fact-hypothesis")
    tcp = curriculum.lesson("tcp-reachability")
    authentication = curriculum.lesson("authentication-boundary")

    assert "$(pwd)" in scope.command
    assert "FACT: current directory" in scope.command
    assert "FACT: TCP" not in scope.command
    assert "без слушающего сервиса" not in tcp.worked_example
    assert "не устанавливает причину или источник отказа" in tcp.worked_example
    assert "аутентификатор" in authentication.term.definition
    assert "не равен установлению реальной личности" in authentication.term.definition
