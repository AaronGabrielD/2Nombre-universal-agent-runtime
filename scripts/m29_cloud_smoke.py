#!/usr/bin/env python3
"""Validate a configured Universal Agent Runtime deployment from outside it."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid


def request_json(url: str, *, method: str = "GET", token: str | None = None, payload: dict | None = None, timeout: int = 30) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw[:500]}
        return exc.code, body
    except urllib.error.URLError as exc:
        return 0, {"error": f"transport error: {exc.reason}"}


def run_smoke(base_url: str, token: str, timeout: int) -> int:
    base_url = base_url.rstrip("/")
    status, health = request_json(f"{base_url}/health", timeout=timeout)
    if status != 200 or health.get("status") != "ok":
        print(f"FAIL health: HTTP {status}")
        return 1
    print("PASS health")

    execution_id = f"m29-{uuid.uuid4().hex}"
    payload = {
        "execution_id": execution_id,
        "run_id": f"smoke-{uuid.uuid4().hex}",
        "worker_id": "smoke-worker",
        "language": "python",
        "code": "print('M29_SMOKE_OK')",
        "timeout_seconds": min(timeout, 30),
        "needs_network": False,
    }
    status, result = request_json(f"{base_url}/execute", method="POST", token=token, payload=payload, timeout=timeout + 5)
    if status != 200 or result.get("status") != "success":
        print(f"FAIL execute: HTTP {status}, status={result.get('status')}")
        return 1
    if "M29_SMOKE_OK" not in result.get("stdout", ""):
        print("FAIL execute: expected marker missing from stdout")
        return 1
    print("PASS authenticated execution")

    status, denied = request_json(f"{base_url}/execute", method="POST", payload=payload, timeout=timeout)
    if status != 401 or denied.get("error") != "unauthorized":
        print(f"FAIL auth boundary: HTTP {status}")
        return 1
    print("PASS authentication boundary")
    print("M29 cloud smoke validation: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("UAR_SMOKE_BASE_URL", ""))
    parser.add_argument("--token", default=os.getenv("RUNTIME_EXECUTION_TOKEN", ""))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("M29_TIMEOUT_SECONDS", "30")))
    args = parser.parse_args(argv)
    if not args.base_url.strip() or not args.token.strip():
        print("FAIL configuration: UAR_SMOKE_BASE_URL and RUNTIME_EXECUTION_TOKEN are required")
        return 2
    if not 1 <= args.timeout <= 120:
        print("FAIL configuration: timeout must be between 1 and 120 seconds")
        return 2
    return run_smoke(args.base_url, args.token, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
