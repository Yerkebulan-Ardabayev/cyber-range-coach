from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, project_root


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(settings.db_url, connect_args=connect_args)
        if settings.db_url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_sqlite_integrity)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _enable_sqlite_integrity(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def initialize(self) -> None:
        migration_config = Config(str(project_root() / "alembic.ini"))
        migration_config.set_main_option(
            "script_location", str(project_root() / "backend" / "migrations")
        )
        migration_config.set_main_option(
            "prepend_sys_path", str(project_root() / "backend" / "src")
        )
        migration_config.set_main_option("sqlalchemy.url", self.settings.db_url.replace("%", "%%"))
        command.upgrade(migration_config, "head")

    def integrity_check(self) -> str:
        with self.engine.connect() as connection:
            if not self.settings.db_url.startswith("sqlite"):
                return "not-sqlite"
            return str(connection.execute(text("PRAGMA integrity_check")).scalar_one())

    def session(self) -> Session:
        return self.session_factory()

    def dependency(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session
