"""Authentication service for durable M26 identities."""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from app.ui.auth import hash_password, verify_password

from .models import UserRecord, UserRole, utc_now_iso
from .repository import UserNotFoundError, UserRepository


class IdentityServiceError(ValueError):
    """Raised when identity configuration or authentication is invalid."""


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Minimal authenticated identity safe to pass across presentation layers."""

    user_id: str
    username: str
    role: UserRole

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    def metadata(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "role": self.role.value,
            "provider": "password",
        }


class IdentityService:
    """Authenticate users against durable storage with optional env bootstrap."""

    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

    def authenticate(self, username: str, password: str) -> AuthenticatedIdentity | None:
        normalized = username.strip() if isinstance(username, str) else ""
        if not normalized or not isinstance(password, str):
            return None

        try:
            user = self.repository.get_by_username(normalized)
        except UserNotFoundError:
            user = self._bootstrap_from_environment(normalized, password)
            if user is None:
                return None

        if not user.enabled or not verify_password(password, user.password_hash):
            return None
        return AuthenticatedIdentity(user.user_id, user.username, user.role)

    def get_identity(self, user_id: str) -> AuthenticatedIdentity:
        try:
            user = self.repository.get_by_id(user_id)
        except UserNotFoundError as exc:
            raise IdentityServiceError(f"Unknown user_id: {user_id}") from exc
        if not user.enabled:
            raise IdentityServiceError("user is disabled")
        return AuthenticatedIdentity(user.user_id, user.username, user.role)

    def ensure_bootstrap_user(self) -> AuthenticatedIdentity | None:
        """Return the configured bootstrap identity only when already persisted."""
        username = os.getenv("UAR_AUTH_USERNAME", "").strip()
        if not username:
            return None
        try:
            user = self.repository.get_by_username(username)
        except UserNotFoundError:
            return None
        if not user.enabled:
            return None
        return AuthenticatedIdentity(user.user_id, user.username, user.role)

    def _bootstrap_from_environment(self, username: str, password: str) -> UserRecord | None:
        configured_username = os.getenv("UAR_AUTH_USERNAME", "").strip()
        encoded_password = os.getenv("UAR_AUTH_PASSWORD_HASH", "").strip()
        if not configured_username or not encoded_password:
            return None
        if not hmac.compare_digest(username, configured_username):
            return None
        if not verify_password(password, encoded_password):
            return None
        try:
            role = UserRole(os.getenv("UAR_AUTH_ROLE", UserRole.USER.value).strip() or UserRole.USER.value)
        except ValueError as exc:
            raise IdentityServiceError("UAR_AUTH_ROLE must be 'user' or 'admin'") from exc

        user = UserRecord(
            username=configured_username,
            password_hash=encoded_password,
            role=role,
        )
        user.validate()
        return self.repository.create(user)

    @staticmethod
    def provision_user(
        repository: UserRepository,
        *,
        username: str,
        password: str,
        role: UserRole = UserRole.USER,
    ) -> UserRecord:
        if not isinstance(password, str) or not password:
            raise IdentityServiceError("password cannot be empty")
        record = UserRecord(
            username=username.strip(),
            password_hash=hash_password(password),
            role=role,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        record.validate()
        return repository.create(record)
