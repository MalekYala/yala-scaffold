#!/usr/bin/env python3
"""End-to-end check for <name> (shape: model).

For a fine-tuning project, "does it work?" means: is the dataset sound, did an
evaluation actually run, and does the resulting model clear the thresholds you
committed to before you started tuning?

That last part matters. Thresholds live in `eval/thresholds.json`, in git, set
*before* a training run. Deciding what counts as good enough after seeing the
number is how a regression gets shipped with a rationalisation attached.

Checks:
  1. dataset      — preflight passes (schema, contract, no train/val leakage)
  2. eval_report  — a report exists, is parseable, and is not stale
  3. eval_scored  — it actually scored examples (zero is a failure, not a pass)
  4. thresholds   — every declared threshold is met

Usage:
    python3 qa_check.py
    python3 qa_check.py --report eval/reports/held-out.json
    python3 qa_check.py --max-age-hours 0      # disable the staleness check

Exit codes:
    0  every check passed
    1  a check failed
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_REPORT = PROJECT_ROOT / "eval" / "reports" / "latest.json"
THRESHOLDS_FILE = PROJECT_ROOT / "eval" / "thresholds.json"


def resolve(report: dict[str, Any], dotted: str) -> Any:
    """Look up 'summary.latency_ms.p50' in the report."""
    node = report
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def run(report_path: Path, max_age_hours: float) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # 1. Dataset integrity. Cheap, and everything downstream depends on it.
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "preflight.py")],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    checks.append(
        {
            "name": "dataset",
            "ok": proc.returncode == 0,
            "detail": (proc.stdout.strip().splitlines() or [""])[-1] if proc.returncode == 0 else proc.stderr.strip()[-400:],
        }
    )

    # 2. An evaluation actually happened, and recently enough to mean anything.
    report: dict[str, Any] | None = None
    if not report_path.is_file():
        checks.append(
            {
                "name": "eval_report",
                "ok": False,
                "detail": f"no report at {report_path} — run `make evaluate`",
            }
        )
    else:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            age_hours = (time.time() - report_path.stat().st_mtime) / 3600.0
            fresh = max_age_hours <= 0 or age_hours <= max_age_hours
            checks.append(
                {
                    "name": "eval_report",
                    "ok": fresh,
                    "detail": f"age {age_hours:.1f}h" + ("" if fresh else f" exceeds max {max_age_hours}h — re-run `make evaluate`"),
                }
            )
        except json.JSONDecodeError as exc:
            checks.append({"name": "eval_report", "ok": False, "detail": f"unparseable: {exc}"})

    # 3. Vacuous success guard: a report that scored nothing is not a pass.
    #    An eval set that silently emptied would otherwise show 0 failures and
    #    look like a perfect run.
    if report is not None:
        scored = resolve(report, "summary.scored") or 0
        request_errors = resolve(report, "summary.request_errors") or 0
        checks.append(
            {
                "name": "eval_scored",
                "ok": scored > 0,
                "detail": f"scored {scored} example(s), {request_errors} request error(s)" + ("" if scored else " — nothing was measured, so nothing is known"),
            }
        )

    # 4. The thresholds committed before the run.
    if report is not None and THRESHOLDS_FILE.is_file():
        try:
            declared = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8")).get("thresholds", [])
        except json.JSONDecodeError as exc:
            checks.append({"name": "thresholds", "ok": False, "detail": f"unparseable: {exc}"})
            declared = []

        for rule in declared:
            metric = rule.get("metric", "")
            want = rule.get("value")
            direction = rule.get("direction", "min")
            actual = resolve(report, metric)

            if actual is None:
                checks.append(
                    {
                        "name": f"threshold:{metric}",
                        "ok": False,
                        "detail": f"{metric} is not present in the report",
                    }
                )
                continue

            ok = actual >= want if direction == "min" else actual <= want
            symbol = ">=" if direction == "min" else "<="
            checks.append(
                {
                    "name": f"threshold:{metric}",
                    "ok": ok,
                    "detail": f"{actual} {symbol} {want}" + ("" if ok else f"  ← FAILED ({rule.get('note', '')})".rstrip()),
                }
            )

    return {
        "status": "ok" if all(c["ok"] for c in checks) else "fail",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate the model against committed thresholds")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=168.0,
        help="fail if the eval report is older than this (0 disables)",
    )
    args = parser.parse_args()

    _t = time.monotonic()
    result = run(args.report, args.max_age_hours)
    elapsed = int((time.monotonic() - _t) * 1000)

    print(json.dumps(result, indent=2))
    print(
        f"[<name>-perf] phase=qa_check duration_ms={elapsed} checks={len(result['checks'])} status={result['status']}",
        file=sys.stderr,
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
