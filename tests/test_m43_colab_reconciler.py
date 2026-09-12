import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app.core.contracts import ExecutionStatus
from app.execution.colab_reconciler import ColabExecutionReconciler, ColabReconcilerError


class _AuthorityHandler(BaseHTTPRequestHandler):
    records = {
        "exec-ok": {
            "execution_id": "exec-ok",
            "status": "success",
            "exit_code": 0,
            "stdout": "remote-ok",
            "stderr": "",
            "duration_ms": 17,
            "artifacts": [],
            "backend": "colab",
        },
    }
    token = "authority-token"

    def do_GET(self):  # noqa: N802
        supplied = self.headers.get("Authorization", "")
        if supplied != f"Bearer {self.token}":
            self.send_response(401)
            self.end_headers()
            return
        execution_id = urlparse(self.path).path.rsplit("/", 1)[-1]
        payload = self.records.get(execution_id)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


class M43ColabReconcilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _AuthorityHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_authoritative_success_is_returned(self):
        reconciler = ColabExecutionReconciler(base_url=self.base_url, token="authority-token")
        result = reconciler.reconcile(execution_id="exec-ok", idempotency_key="key-1")
        self.assertIsNotNone(result)
        self.assertEqual(result.execution_id, "exec-ok")
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.stdout, "remote-ok")

    def test_unknown_execution_returns_none(self):
        reconciler = ColabExecutionReconciler(base_url=self.base_url, token="authority-token")
        self.assertIsNone(reconciler.reconcile(execution_id="missing", idempotency_key="key-1"))

    def test_remote_authentication_failure_is_reported(self):
        reconciler = ColabExecutionReconciler(base_url=self.base_url, token="wrong-token")
        with self.assertRaises(ColabReconcilerError) as ctx:
            reconciler.reconcile(execution_id="exec-ok", idempotency_key="key-1")
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_invalid_remote_execution_id_is_rejected(self):
        _AuthorityHandler.records["exec-bad"] = {
            "execution_id": "other-id",
            "status": "success",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "duration_ms": 1,
            "artifacts": [],
            "backend": "colab",
        }
        reconciler = ColabExecutionReconciler(base_url=self.base_url, token="authority-token")
        with self.assertRaises(ColabReconcilerError):
            reconciler.reconcile(execution_id="exec-bad", idempotency_key="key-1")

    def test_nonempty_idempotency_key_is_required(self):
        reconciler = ColabExecutionReconciler(base_url=self.base_url, token="authority-token")
        with self.assertRaises(ColabReconcilerError):
            reconciler.reconcile(execution_id="exec-ok", idempotency_key="")


if __name__ == "__main__":
    unittest.main()
