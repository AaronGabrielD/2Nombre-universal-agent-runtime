"""Authorization boundaries between authenticated identities and runtime runs."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.models import RunContext

from .service import AuthenticatedIdentity


class RunAccessDeniedError(PermissionError):
    """Raised when an identity attempts to access another user's run."""


@dataclass(frozen=True, slots=True)
class RunAuthorizationService:
    """Enforce owner isolation while allowing explicitly privileged admins."""

    owner_metadata_key: str = "owner_user_id"

    def can_access(self, identity: AuthenticatedIdentity, context: RunContext) -> bool:
        if identity.is_admin:
            return True
        return context.metadata.get(self.owner_metadata_key) == identity.user_id

    def require_access(self, identity: AuthenticatedIdentity, context: RunContext) -> None:
        if not self.can_access(identity, context):
            raise RunAccessDeniedError("identity is not authorized for this run")

    def owner_metadata(self, identity: AuthenticatedIdentity) -> dict[str, str]:
        return {
            self.owner_metadata_key: identity.user_id,
            "owner_username": identity.username,
        }
