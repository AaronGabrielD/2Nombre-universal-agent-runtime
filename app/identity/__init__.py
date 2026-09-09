"""Durable user identity primitives for M26."""

from .models import UserRecord, UserRole
from .repository import InMemoryUserRepository, SQLiteUserRepository, UserNotFoundError
from .service import IdentityService, IdentityServiceError

__all__ = [
    "IdentityService",
    "IdentityServiceError",
    "InMemoryUserRepository",
    "SQLiteUserRepository",
    "UserNotFoundError",
    "UserRecord",
    "UserRole",
]
