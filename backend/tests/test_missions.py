from __future__ import annotations

import io
import tarfile
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from cyber_range_coach.errors import AppError
from cyber_range_coach.models import MissionRun
from cyber_range_coach.services.mission_grader import (
    MissionGradeStatus,
    MissionGradingContract,
    grade_mission,
)
from cyber_range_coach.services.missions import (
    complete_mission_run,
    mission_seed_archive,
    plan_missions,
)
from cyber_range_coach.services.ssh import RangeRunner

from .conftest import csrf_headers


def _mission_item(plan: object, mission_id: str):
    return next(item for item in plan.items if item.mission_id == mission_id)


def _correct_submission(
    client: TestClient, mission_id: str, variant_id: str
) -> tuple[str, str, dict[str, str]]:
    variant = client.app.state.mission_catalog.variant(mission_id, variant_id)
    artifact = variant.grading.artifact.accepted_values[0]
    explanation = "Маркер trace указывает на нужный сектор."
    if mission_id == "why-command-failed":
        explanation = "Это ошибка оболочки: в Bash нужен правильный флаг или аргумент."
    facts = {field.id: field.accepted_values[0] for field in variant.grading.facts}
    return artifact, explanation, facts


def test_mission_catalog_has_the_two_stage2_scenarios_and_existing_techniques(client) -> None:
    catalog = client.app.state.mission_catalog
    assert set(catalog.missions) == {"magpie-missing-clue", "why-command-failed"}
    assert sum(len(mission.variants) for mission in catalog.missions.values()) == 7
    assert all(
        technique_id in client.app.state.command_catalog.techniques
        for mission in catalog.missions.values()
        for technique_id in mission.technique_ids
    )
    assert all(mission.requires_free_text for mission in catalog.missions.values())


def test_mission_grader_accepts_only_known_artifact_and_requires_explanation() -> None:
    contract = MissionGradingContract.model_validate(
        {
            "artifact": {
                "accepted_values": ["trace: marker=ORBIT-41"],
                "review_patterns": [r"^trace:\s*marker=[A-Z]+-[0-9]+$"],
            },
            "facts": [
                {
                    "id": "marker",
                    "label": "Маркер",
                    "accepted_values": ["ORBIT-41"],
                },
                {
                    "id": "sector",
                    "label": "Сектор",
                    "accepted_values": ["west"],
                },
            ],
            "explanation": {
                "expected_concepts": [["маркер", "marker"], ["сектор", "sector"]],
                "debrief": "Разбор открывается только после отправки.",
            },
        }
    )
    facts = {"marker": "ORBIT-41", "sector": "west"}
    solved = grade_mission(
        "trace: marker=ORBIT-41", facts, "Маркер ведёт в нужный сектор.", contract
    )
    fake = grade_mission("fabricated terminal output", facts, "Маркер и сектор.", contract)
    unknown = grade_mission("trace: marker=OTHER-99", facts, "Маркер и сектор.", contract)
    unexplained = grade_mission("trace: marker=ORBIT-41", {}, "маркер сектор", contract)
    negation = grade_mission(
        "trace: marker=ORBIT-41",
        {},
        "Этот маркер вообще не связан с сектором",
        contract,
    )
    assert solved.status == MissionGradeStatus.solved
    assert fake.status == MissionGradeStatus.wrong_artifact
    assert fake.status != MissionGradeStatus.solved
    assert unknown.status == MissionGradeStatus.needs_review
    assert unexplained.status == MissionGradeStatus.unexplained
    assert negation.status != MissionGradeStatus.solved
    assert solved.explanation_accepted is False


def test_completed_mission_uses_next_synthetic_variant_without_needing_command_history(client) -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    catalog = client.app.state.mission_catalog
    with client.app.state.db.session_factory() as session:
        first_plan = plan_missions(session, catalog)
        first = _mission_item(first_plan, "magpie-missing-clue")
        first_variant = catalog.variant(first.mission_id, first.variant_id)
        result = complete_mission_run(
            session,
            catalog,
            attempt_key="magpie-variant-attempt-0001",
            mission_id=first.mission_id,
            variant_id=first.variant_id,
            artifact=first_variant.grading.artifact.accepted_values[0],
        explanation="Маркер trace связан с сектором west.",
        structured_facts={
            field.id: field.accepted_values[0] for field in first_variant.grading.facts
        },
            now=now,
        )
        second = _mission_item(plan_missions(session, catalog), "magpie-missing-clue")
        row = session.scalar(select(MissionRun).where(MissionRun.id == result.run_id))
    assert result.status == MissionGradeStatus.solved
    assert second.variant_id != first.variant_id
    assert second.title == first.title
    assert second.final_artifact_prompt == first.final_artifact_prompt
    assert row is not None
    assert row.evidence_kind == "mission_final_artifact"
    assert not hasattr(row, "command_sequence")


def test_mission_api_saves_a_draft_hides_solution_until_response_and_is_idempotent(
    client: TestClient,
) -> None:
    plan = client.get("/api/v2/missions/plan")
    assert plan.status_code == 200
    item = next(value for value in plan.json()["items"] if value["mission_id"] == "magpie-missing-clue")
    serialized = str(item)
    assert "grading" not in item
    assert "debrief" not in serialized
    artifact, explanation, structured_facts = _correct_submission(
        client, item["mission_id"], item["variant_id"]
    )
    payload = {
        "mission_id": item["mission_id"],
        "variant_id": item["variant_id"],
        "artifact": artifact,
        "explanation": explanation,
        "structured_facts": structured_facts,
    }
    attempt_key = "mission-api-attempt-0001"
    draft = client.put(f"/api/v2/missions/attempts/{attempt_key}/draft", json=payload)
    assert draft.status_code == 200
    restored = client.get("/api/v2/missions/plan")
    restored_item = next(
        value for value in restored.json()["items"] if value["mission_id"] == item["mission_id"]
    )
    assert restored_item["draft_attempt_key"] == attempt_key
    assert restored_item["draft_artifact"] == artifact
    completed = client.post(f"/api/v2/missions/attempts/{attempt_key}/complete", json=payload)
    duplicate = client.post(f"/api/v2/missions/attempts/{attempt_key}/complete", json=payload)
    assert completed.status_code == 200
    assert completed.json()["status"] == "solved"
    assert completed.json()["free_text_review_status"] == "not_assessed"
    assert "debrief" in completed.json()
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    with client.app.state.db.session_factory() as session:
        count = session.scalar(select(func.count()).select_from(MissionRun))
    assert count == 1


def test_unknown_mission_variant_needs_review_without_becoming_a_success(client: TestClient) -> None:
    plan = client.get("/api/v2/missions/plan").json()
    item = next(value for value in plan["items"] if value["mission_id"] == "magpie-missing-clue")
    response = client.post(
        "/api/v2/missions/attempts/mission-review-attempt-0001/complete",
        json={
            "mission_id": item["mission_id"],
            "variant_id": item["variant_id"],
            "artifact": "trace: marker=UNKNOWN-99",
            "explanation": "Маркер связан с сектором.",
            "structured_facts": {},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"


def test_terminal_mission_plan_hides_files_and_answers(client) -> None:
    with client.app.state.db.session_factory() as session:
        plan = plan_missions(session, client.app.state.mission_catalog)
    magpie = _mission_item(plan, "magpie-missing-clue")
    assert magpie.delivery == "terminal"
    assert magpie.prepared_data == []
    assert magpie.mission_directory == f"~/missions/{magpie.variant_id}"
    public = magpie.model_dump_json()
    variant = client.app.state.mission_catalog.variant("magpie-missing-clue", magpie.variant_id)
    for fact in variant.grading.facts:
        for value in fact.accepted_values:
            assert value not in public, value
    screen = _mission_item(plan, "why-command-failed")
    assert screen.delivery == "screen"
    assert screen.prepared_data


def test_seed_archive_holds_variant_files_with_real_newlines(client) -> None:
    catalog = client.app.state.mission_catalog
    mission = catalog.missions["magpie-missing-clue"]
    variant = mission.variants[0]
    archive = mission_seed_archive(mission, variant)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        names = tar.getnames()
        for entry in variant.prepared_data:
            assert entry.path in names
            member = tar.getmember(entry.path)
            assert not member.name.startswith("/") and ".." not in member.name.split("/")
            if entry.kind == "text":
                data = tar.extractfile(member).read().decode()  # type: ignore[union-attr]
                assert "\\n" not in data
                assert data.endswith("\n")
    with pytest.raises(AppError):
        mission_seed_archive(catalog.missions["why-command-failed"], catalog.missions["why-command-failed"].variants[0])


def test_seed_endpoint_writes_only_the_variant_directory(client, monkeypatch) -> None:
    calls: list[tuple[str, bytes]] = []

    async def fake_seed(runner: object, variant_id: str, archive: bytes) -> None:
        assert isinstance(runner, RangeRunner)
        calls.append((variant_id, archive))

    monkeypatch.setattr("cyber_range_coach.routers.missions.seed_student_missions", fake_seed)
    client.cookies.set("crc_csrf", "test-csrf")
    variant_id = client.app.state.mission_catalog.missions["magpie-missing-clue"].variants[0].id
    response = client.post(
        f"/api/v2/missions/magpie-missing-clue/variants/{variant_id}/seed",
        headers=csrf_headers("operator"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["directory"] == f"~/missions/{variant_id}"
    assert calls and calls[0][0] == variant_id
    refused = client.post(
        "/api/v2/missions/why-command-failed/variants/"
        + client.app.state.mission_catalog.missions["why-command-failed"].variants[0].id
        + "/seed",
        headers=csrf_headers("operator"),
    )
    assert refused.status_code == 409
    viewer = client.post(
        f"/api/v2/missions/magpie-missing-clue/variants/{variant_id}/seed",
        headers=csrf_headers("viewer"),
    )
    assert viewer.status_code == 403
    assert len(calls) == 1


def test_seed_without_linux_host_is_a_clear_conflict(client) -> None:
    client.cookies.set("crc_csrf", "test-csrf")
    variant_id = client.app.state.mission_catalog.missions["magpie-missing-clue"].variants[0].id
    response = client.post(
        f"/api/v2/missions/magpie-missing-clue/variants/{variant_id}/seed",
        headers=csrf_headers("operator"),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "linux_host_unconfirmed"

