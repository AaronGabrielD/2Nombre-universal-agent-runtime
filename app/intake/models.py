"""Provider-neutral normalized records for universal input ingestion."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class IngestStrategy(StrEnum):
    INLINE_TEXT = "inline_text"
    REMOTE_FILE_UPLOAD = "remote_file_upload"
    LOCAL_PARSER = "local_parser"
    BINARY_UNINTERPRETED = "binary_uninterpreted"


@dataclass(frozen=True, slots=True)
class IntakeFile:
    """Input metadata and optional inline text supplied by the caller."""

    name: str
    mime_type: str | None = None
    size_bytes: int = 0
    source_ref: str | None = None
    inline_text: str | None = None

    def validate(self, *, max_size_bytes: int) -> None:
        if not self.name.strip():
            raise ValueError("file name cannot be empty")
        if self.size_bytes < 0:
            raise ValueError("file size cannot be negative")
        if self.size_bytes > max_size_bytes:
            raise ValueError(
                f"file exceeds configured limit: {self.size_bytes} > {max_size_bytes} bytes"
            )
        if self.inline_text is not None and not (self.mime_type or "").lower().startswith("text/"):
            raise ValueError("inline_text is only allowed for text MIME types")


@dataclass(frozen=True, slots=True)
class IntakeItem:
    """Normalized intake decision for one file."""

    intake_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    mime_type: str | None = None
    size_bytes: int = 0
    strategy: IngestStrategy = IngestStrategy.BINARY_UNINTERPRETED
    reason: str = ""
    source_ref: str | None = None
    inline_text: str | None = None


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """Output consumed by later orchestration modules."""

    run_id: str
    objective: str
    items: tuple[IntakeItem, ...]
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
