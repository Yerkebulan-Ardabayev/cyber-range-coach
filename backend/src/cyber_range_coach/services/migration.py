from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models import Note


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_v1_notes(database_path: Path) -> dict[str, Any]:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    source_hash = file_sha256(database_path)
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"v1 database integrity check failed: {integrity}")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(note)")}
        expected = {
            "id",
            "lab_id",
            "date",
            "goal",
            "hypothesis",
            "commands",
            "results",
            "conclusion",
            "mistakes",
            "learned",
        }
        if not expected.issubset(columns):
            raise RuntimeError("v1 note table is missing required columns")
        rows = [dict(row) for row in connection.execute("SELECT * FROM note ORDER BY id")]
    finally:
        connection.close()
    notes: list[dict[str, Any]] = []
    for row in rows:
        body_parts = []
        for label, field in (
            ("Цель", "goal"),
            ("Гипотеза", "hypothesis"),
            ("Команды", "commands"),
            ("Результаты", "results"),
            ("Вывод", "conclusion"),
            ("Ошибки", "mistakes"),
            ("Изучено", "learned"),
            ("Ручная заметка", "manual_paragraph"),
        ):
            value = str(row.get(field) or "").strip()
            if value:
                body_parts.append(f"## {label}\n\n{value}")
        notes.append(
            {
                "source_v1_id": row["id"],
                "lesson_id": row["lab_id"],
                "date": row["date"],
                "title": f"Полевая заметка v1: {row['lab_id']}",
                "body": "\n\n".join(body_parts),
            }
        )
    return {
        "format": "cyber-range-coach-v1-notes",
        "version": 1,
        "source_database_sha256": source_hash,
        "note_count": len(notes),
        "notes": notes,
    }


def import_v1_notes(session: Session, payload: dict[str, Any]) -> dict[str, int]:
    if payload.get("format") != "cyber-range-coach-v1-notes" or payload.get("version") != 1:
        raise AppError(422, "invalid_v1_export", "Файл не является поддерживаемым экспортом v1.")
    source_hash = str(payload.get("source_database_sha256") or "")
    if len(source_hash) != 64:
        raise AppError(422, "invalid_source_hash", "В экспорте отсутствует SHA-256 исходной базы.")
    notes = payload.get("notes")
    if not isinstance(notes, list) or payload.get("note_count") != len(notes):
        raise AppError(422, "invalid_note_count", "Количество заметок в экспорте не сходится.")
    imported = 0
    skipped = 0
    for item in notes:
        source_id = int(item["source_v1_id"])
        existing = session.scalar(
            select(Note).where(Note.source_v1_id == source_id, Note.source_hash == source_hash)
        )
        if existing:
            skipped += 1
            continue
        session.add(
            Note(
                title=str(item.get("title") or f"Полевая заметка v1 #{source_id}"),
                body=str(item.get("body") or ""),
                lesson_id=str(item.get("lesson_id") or "") or None,
                source_v1_id=source_id,
                source_hash=source_hash,
            )
        )
        imported += 1
    session.commit()
    return {"imported": imported, "skipped": skipped}


def write_v1_export(database_path: Path, output_path: Path) -> None:
    payload = export_v1_notes(database_path)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
