from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from cyber_range_coach.models import (
    AssessmentWindow,
    CommandAttempt,
    CommandPracticeState,
    HelpEvent,
)
from cyber_range_coach.services.command_practice import (
    CommandCatalog,
    SourceCoverage,
    complete_command_attempt,
    complete_command_observation,
    plan_command_practice,
    reveal_command_hint,
    reveal_command_reference,
    save_command_draft,
)
from cyber_range_coach.services.recall_grader import (
    PermutableAnswer,
    RecallContract,
    RecallReason,
    grade_recall,
)


def _facts(catalog: CommandCatalog, technique_id: str) -> dict[str, str]:
    return {
        field.id: field.accepted_values[0]
        for field in catalog.challenge(technique_id).observation.fields
    }


def test_command_catalog_covers_every_source_block_and_has_no_images(settings) -> None:
    catalog = CommandCatalog(settings.command_catalog_dir)
    assert len(catalog.sources) == 27
    assert len(catalog.techniques) == 169
    assert len(catalog.challenges) == len(catalog.techniques)
    assert len(catalog.coverage) == sum(source.block_count for source in catalog.sources)
    assert all(source.embedded_images == 0 for source in catalog.sources)
    assert all(catalog.challenges[identifier].hints[0].level == 1 for identifier in catalog.techniques)
    assert all(catalog.challenges[identifier].context.named_inputs for identifier in catalog.techniques)
    assert all(
        catalog.challenges[identifier].observation.fields
        or catalog.challenges[identifier].observation.output_source == "pending"
        for identifier in catalog.techniques
    )


def test_both_environments_are_merged_and_windows_waits_for_a_stand(settings) -> None:
    """Both environments share one catalog, but Windows cannot be run yet."""
    catalog = CommandCatalog(settings.command_catalog_dir)
    bash = [item for item in catalog.techniques.values() if item.shell == "bash"]
    cmd = [item for item in catalog.techniques.values() if item.shell == "cmd"]
    assert len(bash) == 73
    assert len(cmd) == 96
    # A rehearsal in the browser is not a run on a stand.
    assert all(item.execution_status == "awaiting_stand" for item in cmd)
    assert all(item.execution_status == "range_ready" for item in bash)
    # Linux find and Windows find are two techniques, not one with two shells.
    families = {(item.family, item.shell) for item in catalog.techniques.values()}
    assert ("find", "bash") in families
    assert ("find", "cmd") in families
    # The challenge shell and the technique shell never drift apart.
    for identifier, technique in catalog.techniques.items():
        assert catalog.challenges[identifier].recall.shell == technique.shell


def test_a_command_block_cannot_be_filed_as_prose(settings) -> None:
    """Gate: a block starting with a command must carry a decision, not prose."""
    catalog = CommandCatalog(settings.command_catalog_dir)
    decided = [item for item in catalog.coverage if item.lead]
    assert decided, "the catalog must mark command blocks of the source"
    assert all(item.status != "reference_only" for item in decided)
    entry = {
        "source": "s.docx", "address": "P001", "status": "reference_only",
        "technique_ids": [], "note": "проза",
    }
    # Without the command mark the same block passes: that mark is the gate.
    SourceCoverage.model_validate(entry)
    with pytest.raises(ValidationError, match="starts with the command"):
        SourceCoverage.model_validate({**entry, "lead": "dir"})
    # A marked block with an honest decision passes.
    SourceCoverage.model_validate({**entry, "lead": "dir", "status": "manual_review"})


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
            "comparison_mode": "exact_or_permuted",
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
    variable = RecallContract.model_validate(
        {
            "shell": "bash",
            "expected_tool": "echo",
            "accepted_answers": ['echo "$NEXT_STEP"'],
        }
    )
    glob = RecallContract.model_validate(
        {"shell": "bash", "expected_tool": "cat", "accepted_answers": ["cat *.key"]}
    )
    assert grade_recall("echo '$NEXT_STEP'", "bash", variable, []).reason != RecallReason.correct
    assert grade_recall("cat '*.key'", "bash", glob, []).reason != RecallReason.correct


def test_independent_recall_uses_project_intervals_and_duplicate_is_idempotent(client) -> None:
    technique_id = "linux-pwd-current-directory"
    catalog = client.app.state.command_catalog
    answer = catalog.challenge(technique_id).recall.accepted_answers[0]
    start = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
    observed: list[int | None] = []
    with client.app.state.db.session_factory() as session:
        attempt_at = start
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
                now=attempt_at,
            )
            observed.append(result.interval_days)
            assert result.next_due_at == attempt_at + timedelta(days=expected_days)
            observed_result = complete_command_observation(
                session,
                catalog,
                attempt_key=f"independent-attempt-{index}",
                technique_id=technique_id,
                structured_observation=_facts(catalog, technique_id),
                free_text="Собственное объяснение.",
                timezone="Asia/Almaty",
                now=attempt_at + timedelta(minutes=1),
            )
            assert observed_result.observation_correct is True
            assert result.next_due_at is not None
            attempt_at = result.next_due_at
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
            now=now,
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
    assert stale_catalog.status_code == 200
    stale_completion = client.post(
        "/api/v2/command-practice/attempts/help-cycle-key-a/complete",
        json={
            **payload,
            "answer": answer,
            "observation_answer": "Повтор со старым ключом.",
            "dont_remember": False,
        },
    )
    assert stale_completion.status_code == 200
    assert stale_completion.json()["reason"] == "correct_with_help"
    assert stale_completion.json()["interval_days"] is None


def test_cmd_recall_keeps_backslash_paths_and_folds_only_switch_case() -> None:
    """cmd.exe is not bash: paths keep backslashes and switches start with a slash."""
    contract = RecallContract.model_validate(
        {
            "shell": "cmd",
            "expected_tool": "dir",
            "accepted_answers": [r"dir /a C:\lab"],
            "significant_flags": ["/a"],
            "other_shell_tools": ["ls", "find"],
            "permutable_answers": [
                PermutableAnswer(prefix=["dir"], groups=[["/a"], [r"C:\lab"]])
            ],
            "comparison_mode": "exact_or_permuted",
        }
    )
    # Posix splitting would turn C:\lab into C:lab and the permutation would miss.
    assert grade_recall(r"dir C:\lab /a", "cmd", contract, []).reason == RecallReason.correct
    # A cmd switch is case insensitive, so /A is not a learner error.
    assert grade_recall(r"dir C:\lab /A", "cmd", contract, []).reason == RecallReason.correct
    # The tool name is case insensitive in cmd.exe as well.
    assert grade_recall(r"DIR C:\lab /a", "cmd", contract, []).reason == RecallReason.correct
    # The separator itself is significant: a lost backslash is a different path.
    assert grade_recall(r"dir C:lab /a", "cmd", contract, []).reason != RecallReason.correct
    # A bash tool in a cmd exercise is a shell error, not a tool error.
    assert grade_recall(r"ls -la C:\lab", "cmd", contract, []).reason == RecallReason.wrong_shell
    # Slash switches are flags here, so a missing significant switch is wrong_flag.
    assert grade_recall(r"dir C:\lab", "cmd", contract, []).reason == RecallReason.wrong_flag


def test_cmd_findstr_pattern_stays_case_sensitive_inside_a_switch() -> None:
    """findstr matches its pattern case sensitively, so /c: argument case counts."""
    contract = RecallContract.model_validate(
        {
            "shell": "cmd",
            "expected_tool": "findstr",
            "accepted_answers": ['findstr /b /c:"OS Name" report.txt'],
            "significant_flags": ["/b", "/c:"],
        }
    )
    assert grade_recall(
        'findstr /b /c:"OS Name" report.txt', "cmd", contract, []
    ).reason == RecallReason.correct
    # A folded switch is the same switch, so the answer stays correct.
    assert grade_recall(
        'findstr /B /c:"OS Name" report.txt', "cmd", contract, []
    ).reason == RecallReason.correct
    assert grade_recall(
        'findstr /b /c:"OS NAME" report.txt', "cmd", contract, []
    ).reason == RecallReason.wrong_flag
    # A quoted pattern must survive as one token, otherwise the phrase splits in two.
    assert grade_recall(
        'findstr /b /c:"OS" report.txt', "cmd", contract, []
    ).reason == RecallReason.wrong_flag
    # An unbalanced quote is not a gradeable answer.
    assert grade_recall(
        'findstr /b /c:"OS Name report.txt', "cmd", contract, []
    ).reason == RecallReason.insufficient_data
    # Right switches, wrong operand: the learner must not be sent to check a switch.
    assert grade_recall(
        'findstr /b /c:"OS Name" other.txt', "cmd", contract, []
    ).reason == RecallReason.insufficient_data


def test_new_practice_mixes_environments_and_overdue_still_wins(client) -> None:
    """One catalog must not bury the other, and a due item still comes first."""
    catalog = client.app.state.command_catalog
    with client.app.state.db.session_factory() as session:
        plan = plan_command_practice(session, catalog, limit=10, available_minutes=60)
        shells = {item.shell for item in plan.items}
        assert shells == {"bash", "cmd"}, shells
        # A single environment may not take the whole session on its own.
        assert 0 < sum(item.shell == "cmd" for item in plan.items) < len(plan.items)

        overdue = "win-vol-volume-label"
        session.add(
            CommandPracticeState(
                technique_id=overdue,
                challenge_version=1,
                data_version=catalog.version,
                timezone="UTC",
                practice_cycle=0,
                current_help_levels=[],
                interval_index=1,
                retry_in_session=False,
                draft_answer="",
                draft_observation_answer="",
                last_attempt_at=datetime(2026, 8, 1, tzinfo=UTC),
                next_due_at=datetime(2026, 8, 2, tzinfo=UTC),
            )
        )
        session.commit()
        plan = plan_command_practice(session, catalog, limit=1, available_minutes=60)
        assert [item.technique_id for item in plan.items] == [overdue]


def test_unverified_variant_is_neutral_and_can_be_rewritten_in_same_window(client) -> None:
    technique_id = "linux-pwd-current-directory"
    catalog = client.app.state.command_catalog
    now = datetime(2026, 9, 6, 6, 0, tzinfo=UTC)
    with client.app.state.db.session_factory() as session:
        before = complete_command_attempt(
            session,
            catalog,
            attempt_key="neutral-unverified-attempt",
            technique_id=technique_id,
            answer_shell="bash",
            answer="pwd extra",
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now,
        )
        state = session.get(CommandPracticeState, technique_id)
        attempt = session.scalar(
            select(CommandAttempt).where(
                CommandAttempt.idempotency_key == "neutral-unverified-attempt"
            )
        )
        assert before.verification_status == "unverified"
        assert before.completed is False
        assert state is not None and state.interval_index == 0
        assert state.next_due_at is None and state.eligible_at is None
        assert attempt is not None and attempt.completed_at is None

        corrected = complete_command_attempt(
            session,
            catalog,
            attempt_key="neutral-unverified-attempt",
            technique_id=technique_id,
            answer_shell="bash",
            answer="pwd",
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now + timedelta(minutes=1),
        )
        assert corrected.correct is True
        assert corrected.independent is True


def test_help_event_survives_new_keys_and_five_immediate_rehearsals_do_not_advance(client) -> None:
    technique_id = "linux-pwd-current-directory"
    catalog = client.app.state.command_catalog
    answer = catalog.challenge(technique_id).recall.accepted_answers[0]
    now = datetime(2026, 9, 6, 7, 0, tzinfo=UTC)
    with client.app.state.db.session_factory() as session:
        disclosure = reveal_command_reference(
            session,
            catalog,
            technique_id=technique_id,
            disclosure_key="cross-device-reference-0001",
            surface="mission_reference",
            timezone="Asia/Almaty",
            now=now,
        )
        duplicate = reveal_command_reference(
            session,
            catalog,
            technique_id=technique_id,
            disclosure_key="cross-device-reference-0001",
            surface="mission_reference",
            timezone="Asia/Almaty",
            now=now + timedelta(hours=1),
        )
        assert disclosure.duplicate is False and duplicate.duplicate is True
        for index in range(5):
            result = complete_command_attempt(
                session,
                catalog,
                attempt_key=f"immediate-rehearsal-{index}",
                technique_id=technique_id,
                answer_shell="bash",
                answer=answer,
                observation_answer="",
                dont_remember=False,
                timezone="Asia/Almaty",
                now=now + timedelta(minutes=index + 1),
            )
            assert result.attempt_type == "rehearsal"
            assert result.interval_days is None
            assert result.independent is False
        state = session.get(CommandPracticeState, technique_id)
        assert state is not None and state.interval_index == 0
        assert _as_utc_for_test(state.eligible_at) == now + timedelta(hours=24)
        assert session.scalar(select(func.count()).select_from(HelpEvent)) == 1


def test_parallel_attempt_keys_share_one_window_and_advance_only_once(client) -> None:
    technique_id = "linux-pwd-current-directory"
    catalog = client.app.state.command_catalog
    answer = catalog.challenge(technique_id).recall.accepted_answers[0]
    now = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)

    with client.app.state.db.session_factory() as first_session:
        first = save_command_draft(
            first_session,
            catalog,
            attempt_key="parallel-tab-a",
            technique_id=technique_id,
            answer_shell="bash",
            answer=answer,
            observation_answer="",
            timezone="Asia/Almaty",
            now=now,
        )
        first_window_id = first.window_id

    with client.app.state.db.session_factory() as second_session:
        second = save_command_draft(
            second_session,
            catalog,
            attempt_key="parallel-tab-b",
            technique_id=technique_id,
            answer_shell="bash",
            answer=answer,
            observation_answer="",
            timezone="Asia/Almaty",
            now=now + timedelta(seconds=1),
        )
        assert second.window_id == first_window_id

    with client.app.state.db.session_factory() as first_session:
        first_result = complete_command_attempt(
            first_session,
            catalog,
            attempt_key="parallel-tab-a",
            technique_id=technique_id,
            answer_shell="bash",
            answer=answer,
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now + timedelta(minutes=1),
        )
        assert first_result.interval_days == 1
        assert first_result.independent is True

    with client.app.state.db.session_factory() as second_session:
        second_result = complete_command_attempt(
            second_session,
            catalog,
            attempt_key="parallel-tab-b",
            technique_id=technique_id,
            answer_shell="bash",
            answer=answer,
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now + timedelta(minutes=2),
        )
        state = second_session.get(CommandPracticeState, technique_id)
        window = second_session.get(AssessmentWindow, first_window_id)
        assert second_result.interval_days is None
        assert second_result.independent is False
        assert state is not None and state.interval_index == 1
        assert window is not None and window.advancement_applied is True


def _as_utc_for_test(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def test_wrong_answer_shows_correction_and_retry_does_not_advance(client) -> None:
    catalog = client.app.state.command_catalog
    technique_id = "linux-pwd-current-directory"
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    with client.app.state.db.session_factory() as session:
        wrong = complete_command_attempt(
            session,
            catalog,
            attempt_key="correction-attempt-0001",
            technique_id=technique_id,
            answer_shell="bash",
            answer="ls",
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now,
        )
        assert wrong.correct is False
        assert wrong.correction is not None
        assert wrong.correction.answer == "pwd"
        assert wrong.correction.purpose
        assert wrong.correction.typical_error
        repeated = complete_command_attempt(
            session,
            catalog,
            attempt_key="correction-attempt-0001",
            technique_id=technique_id,
            answer_shell="bash",
            answer="ls",
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now,
        )
        assert repeated.duplicate is True
        assert repeated.correction is not None
        retry = complete_command_attempt(
            session,
            catalog,
            attempt_key="correction-attempt-0002",
            technique_id=technique_id,
            answer_shell="bash",
            answer="pwd",
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now + timedelta(minutes=1),
        )
        state = session.get(CommandPracticeState, technique_id)
        assert state is not None
        assert retry.correct is True
        assert retry.independent is False
        assert retry.interval_days is None
        assert retry.correction is None
        assert state.interval_index == 0


def test_correct_and_unverified_answers_do_not_reveal_correction(client) -> None:
    catalog = client.app.state.command_catalog
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    with client.app.state.db.session_factory() as session:
        correct = complete_command_attempt(
            session,
            catalog,
            attempt_key="no-correction-0001",
            technique_id="linux-pwd-current-directory",
            answer_shell="bash",
            answer="pwd",
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=now,
        )
        assert correct.correct is True
        assert correct.correction is None


def test_pending_windows_output_skips_the_observation_step(client) -> None:
    catalog = client.app.state.command_catalog
    technique_id = "win-systeminfo-full-configuration"
    assert catalog.challenge(technique_id).observation.output_source == "pending"
    with client.app.state.db.session_factory() as session:
        result = complete_command_attempt(
            session,
            catalog,
            attempt_key="pending-output-0001",
            technique_id=technique_id,
            answer_shell="cmd",
            answer="systeminfo",
            observation_answer="",
            dont_remember=False,
            timezone="Asia/Almaty",
            now=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )
    assert result.correct is True
    assert result.completed is True
    assert result.observation_example is None
    assert result.observation_fields == []

