from __future__ import annotations

import hashlib
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
    assert revision == "20260821_0002"
    assert fts == 2
    assert "relay_source_ip" in linux_host_columns


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
