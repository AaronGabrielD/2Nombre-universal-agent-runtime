"""Small dependency-free migration runner for durable SQLite stores."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Sequence


class MigrationError(RuntimeError):
    """Raised when migrations cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]

    def validate(self) -> None:
        if self.version < 1:
            raise MigrationError("migration version must be >= 1")
        if not self.name.strip():
            raise MigrationError("migration name cannot be empty")


class MigrationRunner:
    """Apply ordered, idempotence-independent migrations exactly once."""

    def __init__(self, database_path: str, migrations: Sequence[Migration]) -> None:
        if not database_path.strip():
            raise ValueError("database_path cannot be empty")
        items = tuple(migrations)
        for migration in items:
            migration.validate()
        versions = [migration.version for migration in items]
        if len(set(versions)) != len(versions):
            raise MigrationError("migration versions must be unique")
        if versions != sorted(versions):
            raise MigrationError("migrations must be supplied in version order")
        self.database_path = database_path
        self.migrations = items

    def current_version(self) -> int:
        with sqlite3.connect(self.database_path) as connection:
            self._ensure_table(connection)
            row = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
            return int(row[0] or 0)

    def migrate(self) -> int:
        try:
            with sqlite3.connect(self.database_path) as connection:
                self._ensure_table(connection)
                current = int(connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0] or 0)
                for migration in self.migrations:
                    if migration.version <= current:
                        continue
                    connection.execute("BEGIN")
                    try:
                        migration.apply(connection)
                        connection.execute(
                            "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                            (migration.version, migration.name),
                        )
                        connection.commit()
                    except Exception as exc:
                        connection.rollback()
                        raise MigrationError(
                            f"migration {migration.version} ({migration.name}) failed: {exc}"
                        ) from exc
                    current = migration.version
                return current
        except sqlite3.Error as exc:
            raise MigrationError(f"SQLite migration failure: {exc}") from exc

    @staticmethod
    def _ensure_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
