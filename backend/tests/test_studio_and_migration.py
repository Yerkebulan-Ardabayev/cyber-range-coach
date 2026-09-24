from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from cyber_range_coach.config import project_root
from cyber_range_coach.services.migration import export_v1_notes


def test_studio_preserves_original_hash_and_requires_validation(client: TestClient) -> None:
    original = b"# Safe lesson\n\nFact and hypothesis are different.\n"
    imported = client.post(
        "/api/v2/studio/import",
        files={"file": ("lesson.md", original, "text/markdown")},
    )
    assert imported.status_code == 201
    source = imported.json()
    assert source["sha256"] == hashlib.sha256(original).hexdigest()
    draft = client.post(
        "/api/v2/studio/drafts",
        json={"title": "Imported lesson", "source_ids": [source["id"]]},
    )
    assert draft.status_code == 201
    blocked = client.post(f"/api/v2/studio/drafts/{draft.json()['id']}/publish")
    assert blocked.status_code == 409
    edited_content = draft.json()["content"]
    edited_content["sections"][0]["source_block_ids"] = []
    edited = client.put(
        f"/api/v2/studio/drafts/{draft.json()['id']}",
        json={"title": "Owner-reviewed lesson", "content": edited_content},
    )
    assert edited.status_code == 200
    invalid = client.post(f"/api/v2/studio/drafts/{draft.json()['id']}/validate")
    assert invalid.status_code == 200
    assert invalid.json()["status"] == "draft"
    edited_content["sections"][0]["source_block_ids"] = draft.json()["covered_block_ids"]
    saved = client.put(
        f"/api/v2/studio/drafts/{draft.json()['id']}",
        json={"title": "Owner-reviewed lesson", "content": edited_content},
    )
    assert saved.status_code == 200
    validated = client.post(f"/api/v2/studio/drafts/{draft.json()['id']}/validate")
    assert validated.status_code == 200
    assert validated.json()["status"] == "validated"
    published = client.post(f"/api/v2/studio/drafts/{draft.json()['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    stored = client.app.state.settings.imports_dir / source["stored_name"]
    assert stored.read_bytes() == original
    assert stored.stat().st_mode & 0o222 == 0


def test_runtime_database_uses_alembic_head_and_fts(client: TestClient) -> None:
    with client.app.state.db.engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
        fts = connection.exec_driver_sql(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('notes_fts', 'source_blocks_fts')"
        ).scalar_one()
        linux_host_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(linux_hosts)")
        }
        lab_run_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(lab_runs)")
        }
    assert revision == "20260924_0006"
    assert "help_used" in lab_run_columns
    assert fts == 2
    assert "relay_source_ip" in linux_host_columns


def test_command_practice_migration_is_additive_on_a_disposable_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    disposable = tmp_path / "disposable-copy.db"
    config = Config(str(project_root() / "alembic.ini"))
    config.set_main_option("script_location", str(project_root() / "backend" / "migrations"))
    config.set_main_option("prepend_sys_path", str(project_root() / "backend" / "src"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{source.as_posix()}")
    command.upgrade(config, "20260821_0002")
    with sqlite3.connect(source) as connection:
        connection.execute(
            "INSERT INTO devices (name, role, token_hash, created_at) VALUES (?, ?, ?, ?)",
            ("existing-owner", "owner", "a" * 64, "2026-08-27 00:00:00"),
        )
        connection.commit()
        tables_before = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    shutil.copy2(source, disposable)
    config.set_main_option("sqlalchemy.url", f"sqlite:///{disposable.as_posix()}")
    command.upgrade(config, "20260827_0003")
    with sqlite3.connect(disposable) as connection:
        tables_after = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables_after - tables_before == {
            "command_practice_states",
            "command_attempts",
        }
        assert connection.execute("SELECT count(*) FROM devices").fetchone() == (1,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260827_0003",
        )
    command.downgrade(config, "20260821_0002")
    with sqlite3.connect(disposable) as connection:
        tables_downgraded = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables_downgraded == tables_before
        assert connection.execute("SELECT count(*) FROM devices").fetchone() == (1,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260821_0002",
        )


def test_mission_run_migration_is_additive_on_a_disposable_copy(tmp_path: Path) -> None:
    source = tmp_path / "stage1.db"
    disposable = tmp_path / "stage2-copy.db"
    config = Config(str(project_root() / "alembic.ini"))
    config.set_main_option("script_location", str(project_root() / "backend" / "migrations"))
    config.set_main_option("prepend_sys_path", str(project_root() / "backend" / "src"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{source.as_posix()}")
    command.upgrade(config, "20260827_0003")
    with sqlite3.connect(source) as connection:
        connection.execute(
            "INSERT INTO devices (name, role, token_hash, created_at) VALUES (?, ?, ?, ?)",
            ("existing-stage1-owner", "owner", "b" * 64, "2026-08-27 00:00:00"),
        )
        connection.commit()
        tables_before = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    shutil.copy2(source, disposable)
    config.set_main_option("sqlalchemy.url", f"sqlite:///{disposable.as_posix()}")
    command.upgrade(config, "20260827_0004")
    with sqlite3.connect(disposable) as connection:
        tables_after = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables_after - tables_before == {"mission_runs"}
        assert connection.execute("SELECT count(*) FROM devices").fetchone() == (1,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260827_0004",
        )
    command.downgrade(config, "20260827_0003")
    with sqlite3.connect(disposable) as connection:
        tables_downgraded = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables_downgraded == tables_before
        assert connection.execute("SELECT count(*) FROM devices").fetchone() == (1,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260827_0003",
        )


def test_assessment_integrity_migration_preserves_existing_learning_rows(
    tmp_path: Path,
) -> None:
    database = tmp_path / "assessment-integrity-copy.db"
    config = Config(str(project_root() / "alembic.ini"))
    config.set_main_option("script_location", str(project_root() / "backend" / "migrations"))
    config.set_main_option("prepend_sys_path", str(project_root() / "backend" / "src"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "20260827_0004")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO command_practice_states (
                technique_id, challenge_version, data_version, timezone,
                practice_cycle, current_help_levels, interval_index,
                retry_in_session, draft_answer, draft_observation_answer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("linux-pwd-current-directory", 1, 1, "UTC", 2, "[]", 3, 0, "pwd", "path"),
        )
        connection.execute(
            """
            INSERT INTO command_attempts (
                idempotency_key, technique_id, challenge_version, data_version,
                practice_cycle, started_at, shell, answer, observation_answer,
                revealed_help, result, evidence_kind, observation_correct, dont_remember
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-command-attempt", "linux-pwd-current-directory", 1, 1, 2,
                "2026-09-01 00:00:00", "bash", "pwd", "path", "[]", "correct",
                "recall", 1, 0,
            ),
        )
        connection.execute(
            """
            INSERT INTO mission_runs (
                idempotency_key, mission_id, mission_version, data_version,
                data_variant, declared_artifact, explanation, grader_status,
                explanation_accepted, evidence_kind, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-mission-run", "linux-first-investigation", 1, 1, "variant-a",
                "artifact", "legacy free text", "correct", 1, "structured", "2026-09-01 00:00:00",
            ),
        )
        connection.commit()

    command.upgrade(config, "20260906_0005")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT interval_index, draft_answer, grading_policy_version "
            "FROM command_practice_states WHERE technique_id = ?",
            ("linux-pwd-current-directory",),
        ).fetchone() == (3, "pwd", 1)
        assert connection.execute(
            "SELECT answer, structured_observation, grading_policy_version "
            "FROM command_attempts WHERE idempotency_key = ?",
            ("legacy-command-attempt",),
        ).fetchone() == ("pwd", "{}", 1)
        assert connection.execute(
            "SELECT explanation, structured_facts, free_text_review_status "
            "FROM mission_runs WHERE idempotency_key = ?",
            ("legacy-mission-run",),
        ).fetchone() == ("legacy free text", "{}", "not_assessed")
        assert any(
            row[2] == "assessment_windows" and row[3] == "window_id"
            for row in connection.execute("PRAGMA foreign_key_list(command_attempts)")
        )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260906_0005",
        )

    command.downgrade(config, "20260827_0004")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT answer FROM command_attempts WHERE idempotency_key = ?",
            ("legacy-command-attempt",),
        ).fetchone() == ("pwd",)
        assert connection.execute(
            "SELECT explanation FROM mission_runs WHERE idempotency_key = ?",
            ("legacy-mission-run",),
        ).fetchone() == ("legacy free text",)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_alembic_downgrade_removes_fts_and_application_schema(client: TestClient) -> None:
    config = Config(str(project_root() / "alembic.ini"))
    config.set_main_option("script_location", str(project_root() / "backend" / "migrations"))
    config.set_main_option("prepend_sys_path", str(project_root() / "backend" / "src"))
    config.set_main_option("sqlalchemy.url", client.app.state.settings.db_url.replace("%", "%%"))
    command.downgrade(config, "base")
    with client.app.state.db.engine.connect() as connection:
        tables = set(
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).scalars()
        )
        triggers = set(
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).scalars()
        )
    assert tables == {"alembic_version"}
    assert triggers == set()


def test_v1_export_contains_only_notes(tmp_path: Path) -> None:
    path = tmp_path / "v1.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE note (
          id INTEGER PRIMARY KEY, lab_id TEXT, date TEXT, goal TEXT, hypothesis TEXT,
          commands TEXT, results TEXT, conclusion TEXT, mistakes TEXT, learned TEXT,
          manual_paragraph TEXT
        );
        CREATE TABLE attempt (id INTEGER PRIMARY KEY, raw_output TEXT);
        INSERT INTO note VALUES (1, 'lab-x', '2026-08-20', 'goal', 'hyp', 'cmd', 'result', 'conclusion', '', 'learned', 'manual');
        INSERT INTO attempt VALUES (99, 'sensitive terminal output');
        """
    )
    connection.commit()
    connection.close()
    payload = export_v1_notes(path)
    serialized = str(payload)
    assert payload["note_count"] == 1
    assert "manual" in payload["notes"][0]["body"]
    assert "sensitive terminal output" not in serialized
