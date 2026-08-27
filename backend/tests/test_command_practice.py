from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from cyber_range_coach.models import CommandAttempt, CommandPracticeState
from cyber_range_coach.services.command_practice import (
    CommandCatalog,
    complete_command_attempt,
    plan_command_practice,
    reveal_command_hint,
    save_command_draft,
)
from cyber_range_coach.services.recall_grader import (
    PermutableAnswer,
    RecallContract,
    RecallReason,
    grade_recall,
)


def test_command_catalog_covers_every_source_block_and_has_no_images(settings) -> None:
    catalog = CommandCatalog(settings.command_catalog_dir)
    assert len(catalog.sources) == 11
    assert len(catalog.techniques) == 73
    assert len(catalog.challenges) == len(catalog.techniques)
    assert len(catalog.coverage) == sum(source.block_count for source in catalog.sources)
    assert all(source.embedded_images == 0 for source in catalog.sources)
    assert all(catalog.challenges[identifier].hints[0].level == 1 for identifier in catalog.techniques)


def test_recall_grader_preserves_case_quotes_and_explicit_flag_permutations() -> None:
    quoted = RecallContract.model_validate(
        {
            "shell": "bash",
            "expected_tool": "grep",
            "accepted_answers": ['grep "two  spaces" sample.txt'],
        }
    )
    assert grade_recall('grep "two  spaces" sample.txt', "bash", quoted, []).reason == (
        RecallReason.correct
    )
    assert grade_recall('grep "two spaces" sample.txt', "bash", quoted, []).reason == (
        RecallReason.insufficient_data
    )
    assert grade_recall('GREP "two  spaces" sample.txt', "bash", quoted, []).reason == (
        RecallReason.wrong_tool
    )
    permutable = RecallContract.model_validate(
        {
            "shell": "bash",
            "expected_tool": "find",
            "accepted_answers": ["find . -type f -perm -111"],
            "significant_flags": ["-type", "-perm"],
            "other_shell_tools": ["Get-ChildItem"],
            "permutable_answers": [
                PermutableAnswer(
                    prefix=["find", "."],
                    groups=[["-type", "f"], ["-perm", "-111"]],
                )
            ],
        }
    )
    assert grade_recall("find . -perm -111 -type f", "bash", permutable, []).reason == (
        RecallReason.correct
    )
    assert grade_recall("find . -type f", "bash", permutable, []).reason == (
        RecallReason.wrong_flag
    )
    assert grade_recall("", "bash", permutable, [], dont_remember=True).reason == (
        RecallReason.insufficient_data
    )
    assert grade_recall(
        "find . -type f -perm -111", "bash", permutable, [1]
    ).reason == RecallReason.correct_with_help
    assert grade_recall(
        "find . -type f -perm -111", "zsh", permutable, []
    ).reason == RecallReason.wrong_shell
    assert grade_recall("Get-ChildItem -Recurse", "bash", permutable, []).reason == (
        RecallReason.wrong_shell
    )


def test_independent_recall_uses_project_intervals_and_duplicate_is_idempotent(client) -> None:
    technique_id = "linux-pwd-current-directory"
    catalog = client.app.state.command_catalog
    answer = catalog.challenge(technique_id).recall.accepted_answers[0]
    start = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
    observed: list[int | None] = []
    with client.app.state.db.session_factory() as session:
        for index, expected_days in enumerate((1, 3, 7, 14, 30), start=1):
            result = complete_command_attempt(
                session,
                catalog,
                attempt_key=f"independent-attempt-{index}",
                technique_id=technique_id,
                answer_shell="bash",
                answer=answer,
                observation_answer="Каталог и путь видны в результате.",
                dont_remember=False,
                timezone="Asia/Almaty",
                now=start + timedelta(days=index),
            )
            observed.append(result.interval_days)
            assert result.next_due_at == start + timedelta(days=index + expected_days)
        state = session.get(CommandPracticeState, technique_id)
        assert state is not None
        assert state.interval_index == 5
        attempts_before = session.scalar(select(func.count()).select_from(CommandAttempt))
        duplicate = complete_command_attempt(
            session,
            catalog,
            attempt_key="independent-attempt-5",
            technique_id=technique_id,
            answer_shell="bash",
            answer=answer,
            observation_answer="Повторная отправка.",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=start + timedelta(days=99),
        )
        attempts_after = session.scalar(select(func.count()).select_from(CommandAttempt))
        assert duplicate.duplicate is True
        assert attempts_after == attempts_before
        assert state.interval_index == 5
    assert observed == [1, 3, 7, 14, 30]


def test_hint_does_not_advance_independent_recall_and_error_preserves_application(client) -> None:
    technique_id = "linux-find-executable-files"
    catalog = client.app.state.command_catalog
    answer = catalog.challenge(technique_id).recall.accepted_answers[0]
    now = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)
    with client.app.state.db.session_factory() as session:
        reveal_command_hint(
            session,
            catalog,
            attempt_key="hinted-attempt-0001",
            technique_id=technique_id,
            answer_shell="bash",
            timezone="Asia/Almaty",
            level=1,
        )
        hinted = complete_command_attempt(
            session,
            catalog,
            attempt_key="hinted-attempt-0001",
            technique_id=technique_id,
            answer_shell="bash",
            answer=answer,
            observation_answer="Вывод содержит путь найденного файла.",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now,
        )
        state = session.get(CommandPracticeState, technique_id)
        assert state is not None
        assert hinted.reason == RecallReason.correct_with_help
        assert hinted.interval_days is None
        assert state.interval_index == 0
        state.applied_in_environment_at = now - timedelta(days=2)
        session.commit()
        forgotten = complete_command_attempt(
            session,
            catalog,
            attempt_key="forgotten-attempt-0002",
            technique_id=technique_id,
            answer_shell="bash",
            answer="cat file.txt",
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now + timedelta(hours=1),
        )
        assert forgotten.reason == RecallReason.wrong_tool
        assert forgotten.retry_in_session is True
        assert state.applied_in_environment_at == now - timedelta(days=2)


def test_draft_survives_and_overdue_practice_is_selected_before_new(client) -> None:
    catalog = client.app.state.command_catalog
    due_id = list(catalog.techniques)[-1]
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    with client.app.state.db.session_factory() as session:
        save_command_draft(
            session,
            catalog,
            attempt_key="draft-attempt-0001",
            technique_id=due_id,
            answer_shell="bash",
            answer="partial command",
            observation_answer="partial observation",
            timezone="Asia/Almaty",
            now=now - timedelta(days=3),
        )
        state = session.get(CommandPracticeState, due_id)
        assert state is not None
        state.next_due_at = now - timedelta(days=2)
        session.commit()
        plan = plan_command_practice(
            session,
            catalog,
            limit=1,
            available_minutes=5,
            now=now,
        )
        assert plan.items[0].technique_id == due_id
        assert plan.items[0].draft_answer == "partial command"
        assert plan.items[0].draft_observation_answer == "partial observation"
        assert plan.items[0].overdue is True
        assert plan.debt_remaining == 0


def test_retry_is_greedy_before_new_material_and_respects_limit(client) -> None:
    catalog = client.app.state.command_catalog
    retry_id = list(catalog.techniques)[-1]
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    with client.app.state.db.session_factory() as session:
        save_command_draft(
            session,
            catalog,
            attempt_key="retry-priority-0001",
            technique_id=retry_id,
            answer_shell="bash",
            answer="",
            observation_answer="",
            timezone="Asia/Almaty",
            now=now,
        )
        state = session.get(CommandPracticeState, retry_id)
        assert state is not None
        state.retry_in_session = True
        state.next_due_at = now + timedelta(days=7)
        session.commit()

        plan = plan_command_practice(
            session,
            catalog,
            limit=1,
            available_minutes=90,
            now=now,
        )
        assert plan.session_limit == 1
        assert len(plan.items) == 1
        assert plan.items[0].technique_id == retry_id
        assert plan.items[0].retry_in_session is True


def test_command_practice_api_records_help_and_is_idempotent(client: TestClient) -> None:
    plan = client.get("/api/v2/command-practice/plan?limit=1&available_minutes=5")
    assert plan.status_code == 200
    item = plan.json()["items"][0]
    technique_id = item["technique_id"]
    answer = client.app.state.command_catalog.challenge(technique_id).recall.accepted_answers[0]
    assert "technique" not in item
    assert "recall" not in item["challenge"]
    assert "text" not in item["challenge"]["hints"][0]
    payload = {"technique_id": technique_id, "shell": "bash", "timezone": "Asia/Almaty"}
    draft = client.put(
        "/api/v2/command-practice/attempts/api-attempt-0001/draft",
        json={**payload, "answer": answer, "observation_answer": "Черновик наблюдения."},
    )
    assert draft.status_code == 200
    restored = client.get("/api/v2/command-practice/plan?limit=1&available_minutes=5")
    assert restored.status_code == 200
    assert restored.json()["items"][0]["draft_observation_answer"] == "Черновик наблюдения."
    hint = client.post(
        "/api/v2/command-practice/attempts/api-attempt-0001/hints/1",
        json=payload,
    )
    assert hint.status_code == 200
    assert hint.json()["revealed_help"] == [1]
    assert [step["level"] for step in hint.json()["hints"]] == [1]
    hidden_catalog = client.get(
        f"/api/v2/command-techniques/{technique_id}?attempt_key=api-attempt-0001"
    )
    assert hidden_catalog.status_code == 403
    for level in (2, 3, 4):
        revealed = client.post(
            f"/api/v2/command-practice/attempts/api-attempt-0001/hints/{level}",
            json=payload,
        )
        assert revealed.status_code == 200
    catalog_card = client.get(
        f"/api/v2/command-techniques/{technique_id}?attempt_key=api-attempt-0001"
    )
    assert catalog_card.status_code == 200
    assert catalog_card.json()["technique"]["id"] == technique_id
    assert "challenge" not in catalog_card.json()
    completion_payload = {
        **payload,
        "answer": answer,
        "observation_answer": "Результат содержит ожидаемый путь и строку.",
        "dont_remember": False,
    }
    completed = client.post(
        "/api/v2/command-practice/attempts/api-attempt-0001/complete",
        json=completion_payload,
    )
    assert completed.status_code == 200
    assert completed.json()["reason"] == "correct_with_help"
    duplicate = client.post(
        "/api/v2/command-practice/attempts/api-attempt-0001/complete",
        json=completion_payload,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True


def test_help_cannot_be_bypassed_with_a_new_attempt_key(client: TestClient) -> None:
    technique_id = "linux-pwd-current-directory"
    answer = client.app.state.command_catalog.challenge(technique_id).recall.accepted_answers[0]
    payload = {"technique_id": technique_id, "shell": "bash", "timezone": "Asia/Almaty"}
    for level in (1, 2, 3, 4):
        revealed = client.post(
            f"/api/v2/command-practice/attempts/help-cycle-key-a/hints/{level}",
            json=payload,
        )
        assert revealed.status_code == 200

    completed = client.post(
        "/api/v2/command-practice/attempts/help-cycle-key-b/complete",
        json={
            **payload,
            "answer": answer,
            "observation_answer": "Команда показывает текущий каталог.",
            "dont_remember": False,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["reason"] == "correct_with_help"
    assert completed.json()["independent"] is False
    assert completed.json()["interval_days"] is None

    stale_catalog = client.get(
        f"/api/v2/command-techniques/{technique_id}?attempt_key=help-cycle-key-a"
    )
    assert stale_catalog.status_code == 403
    stale_completion = client.post(
        "/api/v2/command-practice/attempts/help-cycle-key-a/complete",
        json={
            **payload,
            "answer": answer,
            "observation_answer": "Повтор со старым ключом.",
            "dont_remember": False,
        },
    )
    assert stale_completion.status_code == 409
