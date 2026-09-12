"""M08 execution gateway contracts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json

from app.core.contracts import ExecutionRequest


@dataclass(frozen=True, slots=True)
class ExecutionBackendInfo:
    """Describes an execution backend without coupling the core to it."""

    backend_id: str
    name: str
    available: bool = True

    def validate(self) -> None:
        if not isinstance(self.backend_id, str) or not self.backend_id.strip():
            raise ValueError("backend_id cannot be empty")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name cannot be empty")
        if not isinstance(self.available, bool):
            raise ValueError("available must be boolean")


@dataclass(frozen=True, slots=True)
class ExecutionAuthorization:
    """Scoped execution grant with cryptographic proof.

    Production gateways require a grant proof and a request-binding proof. The
    first covers authorization scope; the second binds that grant to one exact
    execution request, including execution ID, code digest, timeout, language,
    network flag, environment digest, and idempotency key.
    Tests may omit both when using the explicit ``test`` execution backend.
    """

    authorized: bool
    reason: str = ""
    gate_id: str | None = None
    run_id: str | None = None
    worker_id: str | None = None
    backend_id: str | None = None
    network_allowed: bool = False
    proof: str | None = None
    request_proof: str | None = None

    def validate(self) -> None:
        if not isinstance(self.authorized, bool):
            raise ValueError("authorized must be boolean")
        if not isinstance(self.reason, str):
            raise ValueError("reason must be a string")
        if not self.authorized and not self.reason.strip():
            raise ValueError("denied authorization requires a reason")
        if self.authorized:
            for name, value in (("run_id", self.run_id), ("worker_id", self.worker_id), ("backend_id", self.backend_id)):
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"authorized execution requires {name}")
        if self.gate_id is not None and (not isinstance(self.gate_id, str) or not self.gate_id.strip()):
            raise ValueError("gate_id must be a non-empty string when supplied")
        if not isinstance(self.network_allowed, bool):
            raise ValueError("network_allowed must be boolean")
        for name, value in (("proof", self.proof), ("request_proof", self.request_proof)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string when supplied")

    def signing_material(self) -> str:
        self.validate()
        return "\x1f".join(
            (
                "1",
                "1" if self.authorized else "0",
                self.reason,
                self.gate_id or "",
                self.run_id or "",
                self.worker_id or "",
                self.backend_id or "",
                "1" if self.network_allowed else "0",
            )
        )


def compute_authorization_proof(secret: str, authorization: ExecutionAuthorization) -> str:
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError("authorization secret must be at least 32 characters")
    return hmac.new(secret.encode("utf-8"), authorization.signing_material().encode("utf-8"), hashlib.sha256).hexdigest()


def _request_fingerprint(request: ExecutionRequest) -> str:
    request.validate()
    environment_material = json.dumps(
        sorted(request.environment.items()),
        separators=(",", ":"),
        ensure_ascii=False,
    )
    code_digest = hashlib.sha256(request.code.encode("utf-8")).hexdigest()
    environment_digest = hashlib.sha256(environment_material.encode("utf-8")).hexdigest()
    return "\x1f".join(
        (
            request.execution_id,
            request.run_id,
            request.worker_id,
            request.language.strip().lower(),
            code_digest,
            str(request.timeout_seconds),
            "1" if request.needs_network else "0",
            environment_digest,
            request.idempotency_key or "",
        )
    )


def compute_request_authorization_proof(
    secret: str,
    authorization: ExecutionAuthorization,
    request: ExecutionRequest,
) -> str:
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError("authorization secret must be at least 32 characters")
    material = "\x1e".join(("request-v1", authorization.signing_material(), _request_fingerprint(request)))
    return hmac.new(secret.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest()


def bind_authorization_to_request(
    secret: str,
    authorization: ExecutionAuthorization,
    request: ExecutionRequest,
) -> ExecutionAuthorization:
    authorization.validate()
    request.validate()
    if not authorization.authorized:
        return authorization
    proof = authorization.proof or compute_authorization_proof(secret, authorization)
    if not hmac.compare_digest(proof, compute_authorization_proof(secret, authorization)):
        raise ValueError("authorization proof is invalid")
    return ExecutionAuthorization(
        authorized=authorization.authorized,
        reason=authorization.reason,
        gate_id=authorization.gate_id,
        run_id=authorization.run_id,
        worker_id=authorization.worker_id,
        backend_id=authorization.backend_id,
        network_allowed=authorization.network_allowed,
        proof=proof,
        request_proof=compute_request_authorization_proof(secret, authorization, request),
    )


def verify_authorization_proof(secret: str, authorization: ExecutionAuthorization) -> bool:
    if not isinstance(secret, str) or len(secret) < 32 or not authorization.proof:
        return False
    expected = compute_authorization_proof(secret, authorization)
    return hmac.compare_digest(expected, authorization.proof)


def verify_request_authorization_proof(
    secret: str,
    authorization: ExecutionAuthorization,
    request: ExecutionRequest,
) -> bool:
    if not isinstance(secret, str) or len(secret) < 32 or not authorization.request_proof:
        return False
    expected = compute_request_authorization_proof(secret, authorization, request)
    return hmac.compare_digest(expected, authorization.request_proof)
