from __future__ import annotations

import unittest

from app.core.config import Settings
from app.core.contracts import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.execution import ExecutionAuthorization, ExecutionBackend, ExecutionBackendInfo, ExecutionGateway
from app.execution.models import compute_authorization_proof


SECRET = "x" * 64


def settings() -> Settings:
    return Settings(
        gemini_api_key=None,
        gemini_model_architect="architect",
        gemini_model_worker="worker",
        gemini_model_supervisor="supervisor",
        gemini_temperature=0.2,
        max_workers=4,
        min_workers=1,
        default_execution_timeout_seconds=60,
        max_uploads_per_message=20,
        max_upload_size_mb=100,
        execution_backend="docker",
        execution_gateway_url=None,
        execution_gateway_token=None,
        execution_authorization_secret=SECRET,
    )


class Backend(ExecutionBackend):
    @property
    def info(self) -> ExecutionBackendInfo:
        return ExecutionBackendInfo("docker", "Docker test backend")

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(
            execution_id=request.execution_id,
            run_id=request.run_id,
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            backend="docker",
        )


class ExecutionAuthorizationProofTests(unittest.TestCase):
    def _grant(self) -> ExecutionAuthorization:
        unsigned = ExecutionAuthorization(
            authorized=True,
            reason="approved",
            gate_id="gate-1",
            run_id="run-1",
            worker_id="worker-1",
            backend_id="docker",
        )
        return ExecutionAuthorization(
            authorized=unsigned.authorized,
            reason=unsigned.reason,
            gate_id=unsigned.gate_id,
            run_id=unsigned.run_id,
            worker_id=unsigned.worker_id,
            backend_id=unsigned.backend_id,
            network_allowed=unsigned.network_allowed,
            proof=compute_authorization_proof(SECRET, unsigned),
        )

    def test_unsigned_authorization_is_rejected_in_production(self):
        gateway = ExecutionGateway(backends=(Backend(),), settings=settings())
        authorization = self._grant()
        forged = ExecutionAuthorization(
            authorized=True,
            reason=authorization.reason,
            gate_id=authorization.gate_id,
            run_id=authorization.run_id,
            worker_id=authorization.worker_id,
            backend_id=authorization.backend_id,
        )
        with self.assertRaisesRegex(RuntimeError, "authorization proof is invalid"):
            gateway.execute(
                ExecutionRequest("exec-1", "run-1", "worker-1", "python", "print('ok')"),
                authorization=forged,
            )

    def test_tampering_with_scoped_fields_invalidates_proof(self):
        gateway = ExecutionGateway(backends=(Backend(),), settings=settings())
        grant = self._grant()
        tampered = ExecutionAuthorization(
            authorized=True,
            reason=grant.reason,
            gate_id=grant.gate_id,
            run_id=grant.run_id,
            worker_id="worker-2",
            backend_id=grant.backend_id,
            network_allowed=grant.network_allowed,
            proof=grant.proof,
        )
        with self.assertRaisesRegex(RuntimeError, "authorization proof is invalid"):
            gateway.execute(
                ExecutionRequest("exec-1", "run-1", "worker-2", "python", "print('ok')"),
                authorization=tampered,
            )

    def test_valid_proof_is_accepted(self):
        gateway = ExecutionGateway(backends=(Backend(),), settings=settings())
        result = gateway.execute(
            ExecutionRequest("exec-1", "run-1", "worker-1", "python", "print('ok')"),
            authorization=self._grant(),
        )
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)


if __name__ == "__main__":
    unittest.main()
