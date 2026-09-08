"""Universal intake orchestration without provider-specific dependencies."""
from __future__ import annotations

from typing import Iterable

from app.core.config import Settings, get_settings
from app.core.models import RunContext
from app.core.states import WorkflowState
from app.session.manager import SessionManager

from .models import IngestStrategy, IntakeFile, IntakeItem, IntakeResult


_INLINE_TEXT_LIMIT_BYTES = 256 * 1024
_TEXT_MIME_PREFIXES = ("text/",)
_REMOTE_MIME_PREFIXES = (
    "image/",
    "audio/",
    "video/",
    "application/pdf",
    "application/json",
    "application/xml",
    "application/zip",
)
_REMOTE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".csv",
    ".md",
    ".rtf",
}


class IntakeService:
    """Normalize user input and register it in one isolated runtime session."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session_manager = session_manager or SessionManager()
        self.settings = settings or get_settings()

    def start_session(
        self,
        objective: str,
        *,
        files: Iterable[IntakeFile] = (),
        metadata: dict[str, str] | None = None,
        inline_text_by_name: dict[str, str] | None = None,
    ) -> IntakeResult:
        objective = objective.strip()
        if not objective:
            raise ValueError("objective cannot be empty")

        files_list = list(files)
        if len(files_list) > self.settings.max_uploads_per_message:
            raise ValueError(
                "too many files: "
                f"{len(files_list)} > {self.settings.max_uploads_per_message}"
            )

        max_size_bytes = self.settings.max_upload_size_mb * 1024 * 1024
        for file in files_list:
            file.validate(max_size_bytes=max_size_bytes)

        context: RunContext = self.session_manager.create_session(metadata=metadata)
        self.session_manager.transition(context.run_id, WorkflowState.INTAKE)
        self.session_manager.add_message(
            context.run_id,
            role="user",
            content=objective,
            metadata={"phase": "intake"},
        )

        normalized: list[IntakeItem] = []
        warnings: list[str] = []
        text_map = inline_text_by_name or {}
        for file in files_list:
            item = self._normalize_file(file, inline_text=text_map.get(file.name))
            normalized.append(item)
            self.session_manager.add_message(
                context.run_id,
                role="system",
                content=f"Registered input file: {file.name}",
                metadata={"intake_id": item.intake_id, "strategy": item.strategy.value},
            )
            if item.strategy == IngestStrategy.BINARY_UNINTERPRETED:
                warnings.append(f"No ingestion adapter selected for {file.name}")

        return IntakeResult(
            run_id=context.run_id,
            objective=objective,
            items=tuple(normalized),
            warnings=tuple(warnings),
            metadata={"file_count": len(normalized)},
        )

    def _normalize_file(self, file: IntakeFile, *, inline_text: str | None) -> IntakeItem:
        mime = (file.mime_type or "").lower().strip()
        name_lower = file.name.lower()

        if mime.startswith(_TEXT_MIME_PREFIXES) and inline_text is not None:
            encoded_size = len(inline_text.encode("utf-8"))
            if encoded_size <= _INLINE_TEXT_LIMIT_BYTES:
                return IntakeItem(
                    name=file.name,
                    mime_type=file.mime_type,
                    size_bytes=file.size_bytes,
                    strategy=IngestStrategy.INLINE_TEXT,
                    reason="small text payload supplied inline",
                    source_ref=file.source_ref,
                    inline_text=inline_text,
                )

        if mime.startswith(_REMOTE_MIME_PREFIXES) or any(
            name_lower.endswith(ext) for ext in _REMOTE_EXTENSIONS
        ):
            return IntakeItem(
                name=file.name,
                mime_type=file.mime_type,
                size_bytes=file.size_bytes,
                strategy=IngestStrategy.REMOTE_FILE_UPLOAD,
                reason="structured or multimodal input requires a file-capable adapter",
                source_ref=file.source_ref,
            )

        if mime.startswith(_TEXT_MIME_PREFIXES):
            return IntakeItem(
                name=file.name,
                mime_type=file.mime_type,
                size_bytes=file.size_bytes,
                strategy=IngestStrategy.LOCAL_PARSER,
                reason="text input was not supplied as an inline payload",
                source_ref=file.source_ref,
            )

        return IntakeItem(
            name=file.name,
            mime_type=file.mime_type,
            size_bytes=file.size_bytes,
            strategy=IngestStrategy.BINARY_UNINTERPRETED,
            reason="no known provider-neutral ingestion strategy",
            source_ref=file.source_ref,
        )
