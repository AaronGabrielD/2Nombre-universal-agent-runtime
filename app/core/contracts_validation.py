"""Shared validation helpers for provider-neutral runtime contracts."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .exceptions import ContractValidationError


def require_non_empty_string(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{name} must be a non-empty string")


def require_string_sequence(name: str, value: Any) -> None:
    if not isinstance(value, (tuple, list)):
        raise ContractValidationError(f"{name} must be a tuple/list of strings")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ContractValidationError(f"{name}[{index}] must be a non-empty string")


def require_string_mapping(name: str, value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{name} must be a mapping")
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ContractValidationError(f"{name} keys must be non-empty strings")
        if not isinstance(item, str):
            raise ContractValidationError(f"{name}[{key!r}] must be a string")


def require_object_mapping(name: str, value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{name} must be an object mapping")


def require_non_negative_integer(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"{name} must be a non-negative integer")


def require_positive_integer(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractValidationError(f"{name} must be a positive integer")
