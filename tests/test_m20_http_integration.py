import os
import threading
import unittest
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
from app.core.contracts import ExecutionRequest, ExecutionStatus
from app.execution.colab import ColabBackendError, ColabExecutionBackend
from app.execution.colab_service import ExecutionServiceConfig, RuntimeColabHTTPServer


class M20HttpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp=TemporaryDirectory(); self._old={k:os.environ.get(k) for k in ("RUNTIME_EXECUTION_TOKEN","RUNTIME_ARTIFACT_ROOT","RUNTIME_ALLOW_NETWORK")}
        os.environ["RUNTIME_EXECUTION_TOKEN"]="integration-test-token"; os.environ["RUNTIME_ARTIFACT_ROOT"]=self._tmp.name; os.environ["RUNTIME_ALLOW_NETWORK"]="false"
        self.config=ExecutionServiceConfig(); self.server=RuntimeColabHTTPServer(("127.0.0.1",0),self.config); self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start(); host,port=self.server.server_address; self.base_url=f"http://{host}:{port}"
        self.backend=ColabExecutionBackend(base_url=self.base_url,token="integration-test-token",timeout_seconds=10)
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2); self._tmp.cleanup()
        for k,v in self._old.items(): os.environ[k]=v if v is not None else os.environ.pop(k,None)
    def request(self,*,code="print('integration-ok')",needs_network=False,execution_id="exec-m20"):
        return ExecutionRequest(execution_id=execution_id,run_id="run-m20",worker_id="worker-m20",language="python",code=code,timeout_seconds=5,needs_network=needs_network,environment={})
    def test_authenticated_http_execution_round_trip(self):
        result=self.backend.execute(self.request()); self.assertEqual(result.execution_id,"exec-m20"); self.assertEqual(result.status,ExecutionStatus.SUCCESS); self.assertIn("integration-ok",result.stdout); self.assertEqual(result.backend,"colab")
    def test_service_rejects_missing_bearer_token(self):
        with self.assertRaises(ColabBackendError) as ctx: ColabExecutionBackend(base_url=self.base_url,timeout_seconds=10).execute(self.request())
        self.assertIn("HTTP 401",str(ctx.exception))
    def test_network_policy_is_enforced_by_remote_service(self):
        result=self.backend.execute(self.request(needs_network=True,execution_id="exec-network")); self.assertEqual(result.status,ExecutionStatus.DENIED); self.assertIn("network execution is disabled",result.stderr)
    def test_artifact_is_returned_and_retrievable(self):
        execution_id="exec-artifact"; code="from pathlib import Path; Path('artifact.txt').write_text('artifact-ok')"; result=self.backend.execute(self.request(code=code,execution_id=execution_id)); self.assertEqual(result.status,ExecutionStatus.SUCCESS); self.assertEqual(len(result.artifacts),1); artifact=result.artifacts[0]; self.assertEqual(artifact.name,"artifact.txt"); self.assertTrue(artifact.uri.startswith(f"artifact://{execution_id}/")); request=Request(f"{self.base_url}/artifacts/{execution_id}/{artifact.name}",headers={"Authorization":"Bearer integration-test-token"});
        with urlopen(request,timeout=5) as response: self.assertEqual(response.read(),b"artifact-ok")

if __name__ == "__main__": unittest.main()
