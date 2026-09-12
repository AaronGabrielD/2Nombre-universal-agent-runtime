"""Structured runtime logging with centralized secret redaction."""
from __future__ import annotations
import json,logging,re
from dataclasses import asdict
from typing import Any
from .models import EventRecord
_SECRET_KEY=re.compile(r"(?:api[_-]?key|token|secret|password|credential|private[_-]?key|authorization|bearer)",re.I)
class JsonEventFormatter(logging.Formatter):
    def format(self,record):
        payload={"timestamp":self.formatTime(record,"%Y-%m-%dT%H:%M:%SZ"),"level":record.levelname,"logger":record.name,"message":record.getMessage()}
        event=getattr(record,"event",None)
        if isinstance(event,EventRecord):payload.update(asdict(event));payload["timestamp"]=event.timestamp.isoformat()
        return json.dumps(_redact(payload),ensure_ascii=False,default=str)
def _redact(value):
    if isinstance(value,dict):
        return {str(k):("[REDACTED]" if _SECRET_KEY.search(str(k)) else _redact(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_redact(v) for v in value]
    if isinstance(value,str):
        # Prevent common bearer/API-key leakage even when embedded in free-form messages.
        value=re.sub(r"(?i)bearer\s+[A-Za-z0-9._~-]+","Bearer [REDACTED]",value);value=re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+",r"\1=[REDACTED]",value);return value
    return value
def configure_logging(level=logging.INFO):
    logger=logging.getLogger("universal_agent_runtime")
    if logger.handlers:logger.setLevel(level);return logger
    handler=logging.StreamHandler();handler.setFormatter(JsonEventFormatter());logger.addHandler(handler);logger.setLevel(level);logger.propagate=False;return logger
def log_event(logger,event,*,level=logging.INFO):logger.log(level,event.short_message,extra={"event":event})
