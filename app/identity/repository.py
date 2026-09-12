"""Durable repositories for M26 identities."""
from __future__ import annotations

import sqlite3
from threading import RLock
from typing import Protocol

from app.core.exceptions import RuntimeErrorBase
from app.persistence.migrations import Migration, MigrationError, MigrationRunner

from .models import UserRecord, UserRole


class UserNotFoundError(RuntimeErrorBase):
    """Raised when a username or user_id does not exist."""


class UserRepositoryError(RuntimeErrorBase):
    """Raised when identity storage cannot be read or written safely."""


class UserRepository(Protocol):
    def create(self, user: UserRecord) -> UserRecord: ...
    def get_by_username(self, username: str) -> UserRecord: ...
    def get_by_id(self, user_id: str) -> UserRecord: ...
    def list_users(self) -> tuple[UserRecord, ...]: ...


class InMemoryUserRepository:
    """Process-local repository used by unit tests and embedded deployments."""

    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}
        self._by_username: dict[str, str] = {}
        self._lock = RLock()

    def create(self, user: UserRecord) -> UserRecord:
        user.validate()
        username = _normalize_username(user.username)
        with self._lock:
            if user.user_id in self._users:
                raise ValueError(f"user_id already exists: {user.user_id}")
            if username in self._by_username:
                raise ValueError(f"username already exists: {user.username}")
            self._users[user.user_id] = user
            self._by_username[username] = user.user_id
        return user

    def get_by_username(self, username: str) -> UserRecord:
        normalized = _normalize_username(username)
        with self._lock:
            user_id = self._by_username.get(normalized)
            if user_id is None:
                raise UserNotFoundError(f"Unknown username: {username}")
            return self._users[user_id]

    def get_by_id(self, user_id: str) -> UserRecord:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id must be a non-empty string")
        with self._lock:
            try:
                return self._users[user_id]
            except KeyError as exc:
                raise UserNotFoundError(f"Unknown user_id: {user_id}") from exc

    def list_users(self) -> tuple[UserRecord, ...]:
        with self._lock:
            return tuple(self._users.values())


class SQLiteUserRepository:
    """SQLite identity repository with explicit schema and strict row validation."""

    def __init__(self, database_path: str) -> None:
        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("database_path cannot be empty")
        self._database_path = database_path
        self._lock = RLock()
        try:
            MigrationRunner(
                self._database_path,
                [Migration(1, "create users table", self._migration_v1)],
            ).migrate()
        except (sqlite3.Error, MigrationError) as exc:
            raise UserRepositoryError(
                f"failed to initialize identity database: {exc}"
            ) from exc

    @staticmethod
    def _migration_v1(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def create(self, user: UserRecord) -> UserRecord:
        user.validate()
        username = _normalize_username(user.username)
        with self._lock:
            try:
                with sqlite3.connect(self._database_path) as connection:
                    connection.execute(
                        """
                        INSERT INTO users
                        (user_id, username, password_hash, role, enabled, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user.user_id,
                            username,
                            user.password_hash,
                            user.role.value,
                            int(user.enabled),
                            user.created_at,
                            user.updated_at,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"identity already exists for username or user_id: {username}"
                ) from exc
            except sqlite3.Error as exc:
                raise UserRepositoryError(
                    f"failed to create identity {username}: {exc}"
                ) from exc
        return UserRecord(
            user_id=user.user_id,
            username=username,
            password_hash=user.password_hash,
            role=user.role,
            enabled=user.enabled,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    def get_by_username(self, username: str) -> UserRecord:
        normalized = _normalize_username(username)
        return self._get(
            "username",
            normalized,
            f"Unknown username: {username}",
        )

    def get_by_id(self, user_id: str) -> UserRecord:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id must be a non-empty string")
        return self._get("user_id", user_id, f"Unknown user_id: {user_id}")

    def _get(self, column: str, value: str, missing: str) -> UserRecord:
        if column not in {"username", "user_id"}:
            raise ValueError("unsupported identity lookup column")
        with self._lock:
            try:
                with sqlite3.connect(self._database_path) as connection:
                    row = connection.execute(
                        f"SELECT user_id, username, password_hash, role, enabled, created_at, updated_at "
                        f"FROM users WHERE {column} = ?",
                        (value,),
                    ).fetchone()
            except sqlite3.Error as exc:
                raise UserRepositoryError(f"failed to read identity: {exc}") from exc
        if row is None:
            raise UserNotFoundError(missing)
        return _row_to_user(row)

    def list_users(self) -> tuple[UserRecord, ...]:
        with self._lock:
            try:
                with sqlite3.connect(self._database_path) as connection:
                    rows = connection.execute(
                        "SELECT user_id, username, password_hash, role, enabled, created_at, updated_at "
                        "FROM users ORDER BY username"
                    ).fetchall()
            except sqlite3.Error as exc:
                raise UserRepositoryError(f"failed to list identities: {exc}") from exc
        return tuple(_row_to_user(row) for row in rows)


def _normalize_username(username: str) -> str:
    if not isinstance(username, str):
        raise ValueError("username must be a string")
    normalized = username.strip()
    if not normalized:
        raise ValueError("username cannot be empty")
    return normalized


def _row_to_user(row: tuple[object, ...]) -> UserRecord:
    try:
        if len(row) != 7:
            raise ValueError("stored identity row has an invalid shape")
        enabled = row[4]
        if isinstance(enabled, bool) or enabled not in (0, 1):
            raise ValueError("enabled flag must be 0 or 1")
        user = UserRecord(
            user_id=row[0],
            username=row[1],
            password_hash=row[2],
            role=UserRole(row[3]),
            enabled=bool(enabled),
            created_at=row[5],
            updated_at=row[6],
        )
        user.validate()
        return user
    except (IndexError, TypeError, ValueError) as exc:
        raise UserRepositoryError("stored identity row is invalid") from exc
