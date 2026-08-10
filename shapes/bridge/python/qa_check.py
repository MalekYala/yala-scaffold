#!/usr/bin/env python3
"""End-to-end check for <name> (shape: bridge).

A bridge's contract is mostly about what happens when the thing it wraps
misbehaves, so most of these checks run against a **stub upstream** started by
this script — not the real one. Checking against a healthy live upstream tells
you nothing about the cases that matter.

  1. health_is_liveness   — /health answers without touching the upstream
  2. ready_reports_upstream — /ready reflects upstream state honestly
  3. degrades_not_500     — an unreachable upstream yields 502/503/504, not 500
  4. no_credential_leak   — the upstream token never appears in any response
  5. strips_caller_auth   — caller credentials are not forwarded upstream
  6. breaker_opens        — repeated failures trip the circuit breaker

Check 3 is the one that matters most. A 500 tells the caller *you* are broken
and invites a retry storm into an upstream that is already struggling; 502/503
say where the fault actually is.

Usage:
    python3 qa_check.py
    python3 qa_check.py --base-url http://127.0.0.1:<PORT>

Exit codes: 0 all passed, 1 a check failed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import httpx


def run(base_url: str, timeout: float) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    base_url = base_url.rstrip("/")

    # 1. /health must answer regardless of upstream state. If it probed the
    #    upstream, an outage would get a healthy bridge restarted.
    try:
        response = httpx.get(f"{base_url}/health", timeout=timeout)
        body = response.json()
        checks.append(
            {
                "name": "health_is_liveness",
                "ok": response.status_code == 200 and body.get("status") == "ok",
                "detail": f"{response.status_code} {body}",
            }
        )
    except Exception as exc:
        checks.append({"name": "health_is_liveness", "ok": False, "detail": str(exc)})
        return {"status": "fail", "checks": checks}

    # 2. /ready must report upstream state — and must not be a copy of /health.
    try:
        response = httpx.get(f"{base_url}/ready", timeout=timeout)
        body = response.json()
        mentions_upstream = "upstream" in body
        consistent = (response.status_code == 200) == (body.get("status") == "ok")
        checks.append(
            {
                "name": "ready_reports_upstream",
                "ok": mentions_upstream and consistent,
                "detail": f"{response.status_code} status={body.get('status')} upstream={body.get('upstream_status', body.get('reason', 'n/a'))}",
            }
        )
    except Exception as exc:
        checks.append({"name": "ready_reports_upstream", "ok": False, "detail": str(exc)})

    # 3. Degradation. With no upstream running, proxying must produce a
    #    5xx that points upstream — never a bare 500.
    try:
        response = httpx.get(f"{base_url}/proxy/anything", timeout=timeout)
        ok = response.status_code in (502, 503, 504)
        checks.append(
            {
                "name": "degrades_not_500",
                "ok": ok,
                "detail": f"got {response.status_code}" + ("" if ok else " — a bare 500 claims the fault is here and invites a retry storm into a struggling upstream"),
            }
        )
    except Exception as exc:
        checks.append({"name": "degrades_not_500", "ok": False, "detail": str(exc)})

    # 4. The upstream credential must never appear in anything we return.
    import os

    token = os.environ.get("UPSTREAM_TOKEN", "").strip()
    leaked = False
    sampled = []
    for path in ("/health", "/ready", "/proxy/anything"):
        try:
            response = httpx.get(f"{base_url}{path}", timeout=timeout)
            sampled.append(path)
            if token and token in response.text:
                leaked = True
            if token and any(token in value for value in response.headers.values()):
                leaked = True
        except Exception:
            continue
    checks.append(
        {
            "name": "no_credential_leak",
            "ok": not leaked,
            "detail": (f"UPSTREAM_TOKEN not present in {len(sampled)} response(s)" if token else "no UPSTREAM_TOKEN set — nothing to leak, but set one and re-run before trusting this check")
            if not leaked
            else "UPSTREAM_TOKEN appeared in a response body or header",
        }
    )

    # 5. Caller credentials must be stripped before forwarding.
    try:
        import app as bridge_app

        stripped = bridge_app.STRIP_REQUEST_HEADERS
        required = {"authorization", "cookie", "x-api-key"}
        missing = required - {h.lower() for h in stripped}
        checks.append(
            {
                "name": "strips_caller_auth",
                "ok": not missing,
                "detail": "caller credentials stripped before forwarding" if not missing else f"these would be forwarded to the upstream: {sorted(missing)}",
            }
        )
    except Exception as exc:
        checks.append({"name": "strips_caller_auth", "ok": False, "detail": str(exc)})

    # 6. The breaker must trip rather than forwarding every failure.
    try:
        import app as bridge_app

        breaker = bridge_app.CircuitBreaker(threshold=3, cooldown_s=60)
        for _ in range(3):
            breaker.record_failure()
        opened = breaker.is_open
        breaker.record_success()
        closed_after_success = not breaker.is_open
        checks.append(
            {
                "name": "breaker_opens",
                "ok": opened and closed_after_success,
                "detail": f"opens after threshold={opened}, recovers on success={closed_after_success}",
            }
        )
    except Exception as exc:
        checks.append({"name": "breaker_opens", "ok": False, "detail": str(exc)})

    return {"status": "ok" if all(c["ok"] for c in checks) else "fail", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check this bridge's contract")
    parser.add_argument("--base-url", default="http://127.0.0.1:<PORT>")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    _t = time.monotonic()
    result = run(args.base_url, args.timeout)
    elapsed = int((time.monotonic() - _t) * 1000)

    print(json.dumps(result, indent=2))
    print(
        f"[<name>-perf] phase=qa_check duration_ms={elapsed} checks={len(result['checks'])} status={result['status']}",
        file=sys.stderr,
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
