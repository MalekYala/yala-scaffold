"""End-to-end check for <name> (shape: analysis).

Verifies that analyze.py produced all required outputs and that the success
sentinel (results/metrics.json) is present and valid. Does NOT re-run the
analysis — that's expensive; use `python3 analyze.py && python3 qa_check.py`.

Run:
    python3 qa_check.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, ClassVar


class Checker:
    name = "<name>"

    REQUIRED_OUTPUTS: ClassVar[list[str]] = [
        "outputs/summary.json",
        "outputs/report.md",
    ]
    # Success sentinel: analyze.py writes this last
    SUCCESS_SENTINEL: ClassVar[str] = "results/metrics.json"
    # Outputs older than this are considered stale (seconds)
    MAX_AGE_S = int(os.environ.get("MAX_OUTPUT_AGE_S", "86400"))

    def run(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        results: dict[str, Any] = {"checks": checks, "status": "ok"}

        # Check 1: success sentinel exists
        sentinel = Path(self.SUCCESS_SENTINEL)
        if not sentinel.exists():
            checks.append(
                {
                    "name": "success_sentinel",
                    "ok": False,
                    "error": f"{self.SUCCESS_SENTINEL} missing — analyze.py never completed successfully?",
                }
            )
            results["status"] = "fail"
            return results
        checks.append({"name": "success_sentinel", "ok": True})

        # Check 2: sentinel is valid JSON with success=true
        try:
            data = json.loads(sentinel.read_text())
            ok = bool(data.get("success"))
            checks.append(
                {
                    "name": "sentinel_valid",
                    "ok": ok,
                    "keys": list(data.keys()),
                }
            )
            if not ok:
                results["status"] = "fail"
        except Exception as exc:
            checks.append({"name": "sentinel_valid", "ok": False, "error": str(exc)})
            results["status"] = "fail"
            return results

        # Check 3: outputs are fresh enough
        age_s = time.time() - sentinel.stat().st_mtime
        fresh = age_s < self.MAX_AGE_S
        checks.append(
            {
                "name": "outputs_fresh",
                "ok": fresh,
                "age_s": round(age_s, 1),
                "max_age_s": self.MAX_AGE_S,
            }
        )
        if not fresh:
            results["status"] = "fail"

        # Check 4: all required outputs present and non-empty
        for rel in self.REQUIRED_OUTPUTS:
            p = Path(rel)
            if not p.exists():
                checks.append({"name": f"output_{p.name}", "ok": False, "error": "missing"})
                results["status"] = "fail"
            elif p.stat().st_size == 0:
                checks.append({"name": f"output_{p.name}", "ok": False, "error": "empty"})
                results["status"] = "fail"
            else:
                checks.append(
                    {
                        "name": f"output_{p.name}",
                        "ok": True,
                        "size_bytes": p.stat().st_size,
                    }
                )

        return results


CHECKER_CLASS = Checker


if __name__ == "__main__":
    result = Checker().run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
