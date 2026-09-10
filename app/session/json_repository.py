"""Provider-neutral durable session repository using one JSON document per run."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from app.core.contracts import ArchitecturePlan, ArtifactRef, ExecutionResult, ExecutionStatus, FinalResult, HumanDecision, HumanDecisionType, WorkerSpec, to_dict
from app.core.models import RunContext
from app.core.states import WorkflowState

from .models import SessionMessage, SessionRecord, WorkerOutput
from .repository import SessionNotFoundError, SessionRepositoryError, validate_session_record_integrity


class JsonFileSessionRepository:
    """Persist each ``SessionRecord`` as atomically replaced JSON."""

    SCHEMA_VERSION = 1

    def __init__(self, root_dir: str) -> None:
        if not isinstance(root_dir, str) or not root_dir.strip():
            raise ValueError("root_dir cannot be empty")
        self.root = Path(root_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def create(self, record: SessionRecord) -> SessionRecord:
        path = self._path(record.context.run_id)
        with self._lock:
            if path.exists():
                raise ValueError(f"run_id already exists: {record.context.run_id}")
            self._write(path, record)
        return record

    def get(self, run_id: str) -> SessionRecord:
        path = self._path(run_id)
        with self._lock:
            if not path.is_file():
                raise SessionNotFoundError(f"Unknown run_id: {run_id}")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                return self._from_dict(payload, expected_run_id=run_id)
            except SessionNotFoundError:
                raise
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise SessionRepositoryError(f"stored session {run_id} is corrupt") from exc

    def save(self, record: SessionRecord) -> SessionRecord:
        path = self._path(record.context.run_id)
        with self._lock:
            if not path.exists():
                raise SessionNotFoundError(f"Unknown run_id: {record.context.run_id}")
            self._write(path, record)
        return record

    def delete(self, run_id: str) -> None:
        path = self._path(run_id)
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError as exc:
                raise SessionNotFoundError(f"Unknown run_id: {run_id}") from exc
            except OSError as exc:
                raise SessionRepositoryError(f"failed to delete session {run_id}: {exc}") from exc

    def contains(self, run_id: str) -> bool:
        return self._path(run_id).is_file()

    def list(self) -> tuple[SessionRecord, ...]:
        with self._lock:
            records = []
            for path in sorted(self.root.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    records.append(self._from_dict(payload, expected_run_id=path.stem))
                except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, SessionRepositoryError) as exc:
                    raise SessionRepositoryError(f"stored session {path.stem} is corrupt") from exc
            return tuple(records)

    def _path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not run_id.strip() or any(ch in run_id for ch in "\\/\x00\r\n"):
            raise ValueError("run_id must be a non-empty safe identifier")
        return self.root / f"{run_id}.json"

    def _write(self, path: Path, record: SessionRecord) -> None:
        validate_session_record_integrity(record)
        payload = {"schema_version": self.SCHEMA_VERSION, "record": _json_safe(to_dict(record))}
        temp = path.with_suffix(path.suffix + ".tmp")
        try:
            temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            os.replace(temp, path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise SessionRepositoryError(f"failed to persist session {record.context.run_id}: {exc}") from exc

    @classmethod
    def _from_dict(cls, payload: dict[str, Any], *, expected_run_id: str | None = None) -> SessionRecord:
        if not isinstance(payload, dict) or payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise SessionRepositoryError("unsupported or invalid session JSON schema")
        raw = payload["record"]
        if not isinstance(raw, dict):
            raise SessionRepositoryError("stored session record must be an object")
        context_raw = raw["context"]
        if not isinstance(context_raw, dict):
            raise SessionRepositoryError("stored session context must be an object")
        context = RunContext(
            run_id=context_raw["run_id"],
            state=WorkflowState(context_raw["state"]),
            created_at=datetime.fromisoformat(context_raw["created_at"]),
            updated_at=datetime.fromisoformat(context_raw["updated_at"]),
            metadata=dict(context_raw.get("metadata", {})),
        )
        if expected_run_id is not None and context.run_id != expected_run_id:
            raise SessionRepositoryError("stored session run_id does not match its storage key")

        record = SessionRecord(
            context=context,
            messages=[SessionMessage(**item) for item in raw.get("messages", [])],
            artifacts=[ArtifactRef(**item) for item in raw.get("artifacts", [])],
            decisions=[HumanDecision(gate_id=item["gate_id"], run_id=item["run_id"], decision=HumanDecisionType(item["decision"]),
                                     feedback=item["feedback"], timestamp=item["timestamp"], actor=item.get("actor", "human"))
                       for item in raw.get("decisions", [])],
            execution_results=[ExecutionResult(execution_id=item["execution_id"], status=ExecutionStatus(item["status"]),
                                               exit_code=item.get("exit_code"), stdout=item["stdout"], stderr=item["stderr"],
                                               duration_ms=item["duration_ms"],
                                               artifacts=tuple(ArtifactRef(**artifact) for artifact in item.get("artifacts", [])),
                                               backend=item.get("backend", "unknown"))
                              for item in raw.get("execution_results", [])],
            worker_outputs={key: WorkerOutput(**value) for key, value in raw.get("worker_outputs", {}).items()},
            architecture_plan=_plan_from_dict(raw["architecture_plan"]) if raw.get("architecture_plan") else None,
            final_result=_final_result_from_dict(raw["final_result"]) if raw.get("final_result") else None,
        )
        return validate_session_record_integrity(record)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value


def _plan_from_dict(raw: dict[str, Any]) -> ArchitecturePlan:
    return ArchitecturePlan(
        plan_id=raw["plan_id"], objective=raw["objective"],
        assumptions=tuple(raw.get("assumptions", [])), constraints=tuple(raw.get("constraints", [])),
        acceptance_criteria=tuple(raw.get("acceptance_criteria", [])), risks=tuple(raw.get("risks", [])),
        required_capabilities=tuple(raw.get("required_capabilities", [])),
        workers=tuple(WorkerSpec(worker_id=item["worker_id"], role=item["role"], mission=item["mission"],
                                 deliverables=tuple(item.get("deliverables", [])), required_tools=tuple(item.get("required_tools", [])),
                                 dependencies=tuple(item.get("dependencies", [])), can_request_human_input=item.get("can_request_human_input", True))
                       for item in raw.get("workers", [])),
    )


def _final_result_from_dict(raw: dict[str, Any]) -> FinalResult:
    return FinalResult(
        run_id=raw["run_id"], status=raw["status"], summary=raw["summary"],
        deliverables=tuple(raw.get("deliverables", [])), tests=tuple(raw.get("tests", [])),
        issues=tuple(raw.get("issues", [])), recommended_next_action=raw.get("recommended_next_action", ""),
    )
