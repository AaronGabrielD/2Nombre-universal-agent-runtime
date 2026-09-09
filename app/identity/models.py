"""Provider-neutral durable identity models for M26."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class UserRecord:
    """Stored application identity; passwords are represented only by hashes."""

    user_id: str = field(default_factory=lambda: str(uuid4()))
    username: str = ""
    password_hash: str = ""
    role: UserRole = UserRole.USER
    enabled: bool = True
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def validate(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id cannot be empty")
        if not self.username.strip():
            raise ValueError("username cannot be empty")
        if not self.password_hash.strip():
            raise ValueError("password_hash cannot be empty")
        if not isinstance(self.role, UserRole):
            raise ValueError("role must be a UserRole")
        if not self.created_at.strip() or not self.updated_at.strip():
            raise ValueError("timestamps cannot be empty")
