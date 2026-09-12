"""Optional Docker execution backend with defense-in-depth isolation."""
from __future__ import annotations
import shutil,subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Sequence
from app.core.contracts import ArtifactRef,ExecutionRequest,ExecutionResult,ExecutionStatus
from .models import ExecutionBackendInfo
from .service import ExecutionBackend
class DockerExecutionBackend(ExecutionBackend):
    def __init__(self,*,image="python:3.12-alpine",docker_binary="docker",allow_network=False,memory="512m",cpus="1.0",pids_limit=128,max_output_bytes=256*1024,artifact_root=None,max_artifacts=20,max_artifact_bytes=10*1024*1024):
        if not isinstance(image,str) or not image.strip() or any(c in image for c in "\r\n"):raise ValueError("image must be a non-empty single-line value")
        if pids_limit<16 or max_output_bytes<1024 or max_artifacts<1 or max_artifact_bytes<1:raise ValueError("Docker safety limits are invalid")
        self.image=image.strip();self.docker_binary=docker_binary;self.allow_network=allow_network;self.memory=memory;self.cpus=cpus;self.pids_limit=pids_limit;self.max_output_bytes=max_output_bytes;self.artifact_root=Path(artifact_root).expanduser().resolve() if artifact_root else None;self.max_artifacts=max_artifacts;self.max_artifact_bytes=max_artifact_bytes
        if self.artifact_root:self.artifact_root.mkdir(parents=True,exist_ok=True)
    @property
    def info(self):return ExecutionBackendInfo("docker","Hardened Docker execution backend",shutil.which(self.docker_binary) is not None)
    def execute(self,request):
        request.validate(max_timeout_seconds=3600);started=monotonic()
        if request.language.strip().lower()!="python":return self._result(request,ExecutionStatus.UNAVAILABLE,"","unsupported language",None,started)
        if not self.info.available:return self._result(request,ExecutionStatus.UNAVAILABLE,"","docker executable is unavailable",None,started)
        if request.needs_network and not self.allow_network:return self._result(request,ExecutionStatus.DENIED,"","network execution is disabled by Docker backend policy",None,started)
        with TemporaryDirectory(prefix=f"uar-docker-{request.execution_id[:12]}-") as temp:
            root=Path(temp).resolve();root.chmod(0o777);(root/"main.py").write_text(request.code,encoding="utf-8");command=self._docker_command(request,root)
            try:completed=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",shell=False,timeout=request.timeout_seconds+5,check=False)
            except subprocess.TimeoutExpired as exc:return self._result(request,ExecutionStatus.TIMEOUT,self._bounded(exc.stdout or ""),self._bounded(exc.stderr or "") or "container execution timed out",None,started)
            except OSError as exc:return self._result(request,ExecutionStatus.ERROR,"",f"docker launch failed: {exc}",None,started)
            stdout=self._bounded(completed.stdout);stderr=self._bounded(completed.stderr);status=ExecutionStatus.SUCCESS if completed.returncode==0 else ExecutionStatus.ERROR;artifacts=self._persist_artifacts(root,request.execution_id)
            return self._result(request,status,stdout,stderr,completed.returncode,started,artifacts)
    def _docker_command(self,request,root):
        network="bridge" if request.needs_network else "none";command=[self.docker_binary,"run","--rm","--pull=never","--network",network,"--read-only","--cap-drop=ALL","--security-opt=no-new-privileges:true","--pids-limit",str(self.pids_limit),"--memory",self.memory,"--cpus",self.cpus,"--tmpfs","/tmp:rw,nosuid,nodev,noexec,size=64m","--user","65532:65532","--mount",f"type=bind,src={root},dst=/workspace,rw","--workdir","/workspace","--env","PYTHONUNBUFFERED=1"]
        for key,value in request.environment.items():
            if self._safe_environment_key(key):command.extend(["--env",f"{key}={value}"])
        command.extend([self.image,"python","-I","/workspace/main.py"]);return command
    def _persist_artifacts(self,root,execution_id):
        if self.artifact_root is None:return ()
        destination_root=(self.artifact_root/execution_id).resolve();destination_root.mkdir(parents=True,exist_ok=True);artifacts=[];total=0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name=="main.py":continue
            size=path.stat().st_size
            if len(artifacts)>=self.max_artifacts or total+size>self.max_artifact_bytes:break
            relative=path.relative_to(root);destination=(destination_root/relative).resolve()
            try:destination.relative_to(destination_root)
            except ValueError:continue
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,destination);total+=size;artifacts.append(ArtifactRef(f"artifact-{execution_id}-{len(artifacts)}",relative.as_posix(),uri=f"artifact://{execution_id}/{relative.as_posix()}"))
        return tuple(artifacts)
    def _bounded(self,value):
        encoded=value.encode("utf-8",errors="replace")
        return value if len(encoded)<=self.max_output_bytes else encoded[:self.max_output_bytes].decode("utf-8",errors="ignore")+"\n[output truncated]"
    @staticmethod
    def _safe_environment_key(key):return isinstance(key,str) and 0<len(key)<=128 and (key[0].isalpha() or key[0]=="_") and all(c.isalnum() or c=="_" for c in key)
    @staticmethod
    def _result(request,status,stdout,stderr,exit_code,started,artifacts=()):return ExecutionResult(execution_id=request.execution_id,run_id=request.run_id,status=status,exit_code=exit_code,stdout=stdout,stderr=stderr,duration_ms=max(0,int((monotonic()-started)*1000)),artifacts=tuple(artifacts),backend="docker")
