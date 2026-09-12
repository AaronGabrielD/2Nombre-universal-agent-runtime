"""Central runtime configuration loaded from environment variables."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse
from .exceptions import RuntimeConfigurationError

def _int_env(name,default,*,minimum=0):
    raw=os.getenv(name,str(default)).strip()
    try:value=int(raw)
    except ValueError as exc:raise RuntimeConfigurationError(f"{name} must be an integer") from exc
    if value<minimum:raise RuntimeConfigurationError(f"{name} must be >= {minimum}")
    return value

def _float_env(name,default):
    try:return float(os.getenv(name,str(default)).strip())
    except ValueError as exc:raise RuntimeConfigurationError(f"{name} must be a number") from exc
@dataclass(frozen=True,slots=True)
class Settings:
    gemini_api_key:str|None=field(repr=False); gemini_model_architect:str; gemini_model_worker:str; gemini_model_supervisor:str; gemini_temperature:float; max_workers:int; min_workers:int; default_execution_timeout_seconds:int; max_uploads_per_message:int; max_upload_size_mb:int; execution_backend:str; execution_gateway_url:str|None; execution_gateway_token:str|None=field(repr=False)
    def validate(self):
        if not isinstance(self.execution_backend,str) or not self.execution_backend.strip():raise RuntimeConfigurationError("EXECUTION_BACKEND cannot be empty")
        if self.execution_backend not in {"colab","docker","test"}:raise RuntimeConfigurationError("EXECUTION_BACKEND must be colab, docker, or test")
        if self.execution_backend=="colab" and not self.execution_gateway_url:raise RuntimeConfigurationError("EXECUTION_GATEWAY_URL is required when EXECUTION_BACKEND=colab")
        if self.execution_gateway_url:
            p=urlparse(self.execution_gateway_url.strip())
            if p.scheme not in {"http","https"} or not p.netloc:raise RuntimeConfigurationError("EXECUTION_GATEWAY_URL must be an absolute HTTP(S) URL")
        if self.execution_gateway_url and not self.execution_gateway_token:raise RuntimeConfigurationError("EXECUTION_GATEWAY_TOKEN is required when EXECUTION_GATEWAY_URL is configured")
        if self.execution_gateway_token and not self.execution_gateway_url:raise RuntimeConfigurationError("EXECUTION_GATEWAY_URL is required when EXECUTION_GATEWAY_TOKEN is configured")
        if not 0<=self.gemini_temperature<=2:raise RuntimeConfigurationError("GEMINI_TEMPERATURE must be between 0 and 2")
        if self.min_workers<1 or self.max_workers<self.min_workers or self.max_workers>32:raise RuntimeConfigurationError("worker limits are invalid or exceed safety ceiling 32")
        if self.max_uploads_per_message<1 or self.max_upload_size_mb<1 or self.default_execution_timeout_seconds<1:raise RuntimeConfigurationError("upload/timeout limits must be positive")
    def require_gemini_key(self):
        if not self.gemini_api_key:raise RuntimeConfigurationError("GEMINI_API_KEY is required for Gemini-backed agents.")
        return self.gemini_api_key
_CACHED=None
def get_settings(*,reload=False):
    global _CACHED
    if _CACHED is not None and not reload:return _CACHED
    settings=Settings(gemini_api_key=os.getenv("GEMINI_API_KEY") or None,gemini_model_architect=os.getenv("GEMINI_MODEL_ARCHITECT","gemini-3.5-flash"),gemini_model_worker=os.getenv("GEMINI_MODEL_WORKER","gemini-3.5-flash"),gemini_model_supervisor=os.getenv("GEMINI_MODEL_SUPERVISOR","gemini-3.5-flash"),gemini_temperature=_float_env("GEMINI_TEMPERATURE",0.2),max_workers=_int_env("MAX_WORKERS",4,minimum=1),min_workers=_int_env("MIN_WORKERS",3,minimum=1),default_execution_timeout_seconds=_int_env("DEFAULT_EXECUTION_TIMEOUT_SECONDS",60,minimum=1),max_uploads_per_message=_int_env("MAX_UPLOADS_PER_MESSAGE",20,minimum=1),max_upload_size_mb=_int_env("MAX_UPLOAD_SIZE_MB",100,minimum=1),execution_backend=os.getenv("EXECUTION_BACKEND","docker").strip().lower(),execution_gateway_url=os.getenv("EXECUTION_GATEWAY_URL") or None,execution_gateway_token=os.getenv("EXECUTION_GATEWAY_TOKEN") or None)
    settings.validate();_CACHED=settings;return settings
