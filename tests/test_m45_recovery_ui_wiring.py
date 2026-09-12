import os
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from app.core.config import Settings
from app.execution.colab_reconciler import ColabExecutionReconciler
from app.execution.reconciliation import ExecutionReconciliationService
from app.runtime.bootstrap import build_runtime


def _settings():
    return Settings(
        gemini_api_key="test-key",
        gemini_model_architect="architect",
        gemini_model_worker="worker",
        gemini_model_supervisor="supervisor",
        gemini_temperature=0.2,
        max_workers=4,
        min_workers=3,
        default_execution_timeout_seconds=60,
        max_uploads_per_message=20,
        max_upload_size_mb=100,
        execution_backend="colab",
        execution_gateway_url="https://example.invalid",
        execution_gateway_token="test-token",
        execution_authorization_secret="test-execution-authorization-secret-1234567890",
    )


class M45RecoveryWiringTests(unittest.TestCase):
    def test_runtime_injects_colab_reconciliation_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "UAR_SESSION_REPOSITORY": "json",
                    "UAR_SESSION_REPOSITORY_PATH": directory,
                    "UAR_IDENTITY_DB_PATH": os.path.join(directory, "users.db"),
                },
                clear=True,
            ):
                application = build_runtime(_settings())

        recovery = application.coordinator.recovery_resume
        self.assertIsInstance(recovery.reconciliation, ExecutionReconciliationService)
        self.assertIsInstance(
            recovery.reconciliation.backend_reconciler,
            ColabExecutionReconciler,
        )

    def test_runtime_leaves_backend_authority_disabled_without_gateway(self):
        settings = replace(
            _settings(),
            execution_backend="test",
            execution_gateway_url=None,
            execution_gateway_token=None,
        )
        settings.validate()
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "UAR_SESSION_REPOSITORY": "json",
                    "UAR_SESSION_REPOSITORY_PATH": directory,
                    "UAR_IDENTITY_DB_PATH": os.path.join(directory, "users.db"),
                },
                clear=True,
            ):
                application = build_runtime(settings)
        self.assertIsNone(application.coordinator.recovery_resume.reconciliation.backend_reconciler)


if __name__ == "__main__":
    unittest.main()
