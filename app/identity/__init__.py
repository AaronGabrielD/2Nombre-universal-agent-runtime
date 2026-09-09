"""Durable user identity and authorization primitives for M26."""

from .authorization import RunAccessDeniedError, RunAuthorizationService
from .models import UserRecord, UserRole
from .repository import InMemoryUserRepository, SQLiteUserRepository, UserNotFoundError
from .service import AuthenticatedIdentity, IdentityService, IdentityServiceError

__all__ = [
    "AuthenticatedIdentity",
    "IdentityService",
    "IdentityServiceError",
    "InMemoryUserRepository",
    "RunAccessDeniedError",
    "RunAuthorizationService",
    "SQLiteUserRepository",
    "UserNotFoundError",
    "UserRecord",
    "UserRole",
]
