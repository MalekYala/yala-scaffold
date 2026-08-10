"""End-to-end health check for <name> (shape: worker).

A worker has no HTTP surface, so health is a combination of:
    1. The heartbeat file is fresh (worker is alive and looping).
    2. The worker process is actually running (container is up).
    3. Recent perf logs show successful processing (no runaway error rate).

Run inside the running container:
    docker compose exec <name> python3 /app/qa_check.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


class Checker:
    name = "<name>"

    def run(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        results: dict[str, Any] = {"checks": checks, "status": "ok"}
        data_dir = Path(os.environ.get("DATA_DIR", "data"))
        heartbeat = data_dir / "heartbeat"
        max_age_s = int(os.environ.get("HEARTBEAT_MAX_AGE_S", "60"))

        # Check 1: heartbeat file exists and is fresh
        try:
            age = time.time() - heartbeat.stat().st_mtime
            ok = age < max_age_s
            checks.append(
                {
                    "name": "heartbeat_fresh",
                    "ok": ok,
                    "age_s": round(age, 1),
                    "max_age_s": max_age_s,
                }
            )
            if not ok:
                results["status"] = "fail"
        except FileNotFoundError:
            checks.append(
                {
                    "name": "heartbeat_fresh",
                    "ok": False,
                    "error": f"heartbeat file {heartbeat} not found — worker never started?",
                }
            )
            results["status"] = "fail"

        # TODO: add checks for worker-specific success signals, e.g.
        #   - queue depth below threshold
        #   - recent jobs_completed count > 0 over the last minute
        #   - error rate from structured perf logs < threshold
        return results


CHECKER_CLASS = Checker


if __name__ == "__main__":
    result = Checker().run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
