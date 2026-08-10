#!/usr/bin/env python3
"""End-to-end check for <name> (shape: browser).

Runs every committed workflow against a locally served fixture site — a real
Chromium, real navigation, real clicks — with no external site involved.

Checks:

  1. workflows_present  — there are workflows to run
  2. every_workflow_asserts — each declares at least one assert_* step
  3. no_time_waits      — no workflow waits on a fixed delay
  4. fixture_serves     — the committed site is reachable
  5. workflows_pass     — every workflow completes with all steps green
  6. detects_breakage   — a deliberately wrong selector FAILS
  7. deterministic      — repeated runs agree
  8. artifacts_on_fail  — a failure leaves a screenshot and page HTML behind

Check 2 is the anti-vacuity rule this kit applies everywhere. A workflow can
visit five pages, match nothing, assert nothing, and report success — the same
family as zero discovered routes, zero exposed MCP tools, zero extracted
records. Navigation completing is not evidence that anything worked.

Check 3 catches the single largest source of browser-test flake before it can
bite: a fixed `sleep` is a bet that CI is at least as fast as your laptop, and
CI loses that bet. It is a static check, so it fails in milliseconds rather
than intermittently at 3am.

Check 6 matters because a harness that cannot fail is worthless. It points a
workflow at a selector that does not exist and requires the run to go red.

Usage:
    python3 qa_check.py
    python3 qa_check.py --repeats 5

Exit codes:
    0  every check passed
    1  a check failed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from fixtures.server import FixtureSite  # noqa: E402
from runner import ASSERTION_STEPS, load_workflow, run_workflow  # noqa: E402

WORKFLOW_DIR = PROJECT_ROOT / "workflows"

# Fixed-delay waiting, in a workflow or in the runner. The reason browser
# suites are flaky, and statically detectable.
SLEEP_PATTERN = re.compile(r'"action"\s*:\s*"(sleep|wait|delay|pause)"', re.I)


def run(repeats: int) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    workflow_files = sorted(WORKFLOW_DIR.glob("*.json"))
    checks.append(
        {
            "name": "workflows_present",
            "ok": bool(workflow_files),
            "detail": f"{len(workflow_files)} workflow(s): {[f.stem for f in workflow_files]}" if workflow_files else f"no workflows in {WORKFLOW_DIR.name}/ — nothing is being automated or checked",
        }
    )
    if not workflow_files:
        return {"status": "fail", "checks": checks}

    # 2. Every workflow must assert something.
    assertionless = []
    for path in workflow_files:
        steps = load_workflow(path).get("steps", [])
        if not any(step.get("action") in ASSERTION_STEPS for step in steps):
            assertionless.append(path.stem)
    checks.append(
        {
            "name": "every_workflow_asserts",
            "ok": not assertionless,
            "detail": "every workflow makes at least one assertion"
            if not assertionless
            else f"no assert_* step in: {assertionless} — these can visit every page, match nothing, and still report success",
        }
    )

    # 3. No time-based waiting anywhere.
    sleepers = [p.stem for p in workflow_files if SLEEP_PATTERN.search(p.read_text(encoding="utf-8"))]
    checks.append(
        {
            "name": "no_time_waits",
            "ok": not sleepers,
            "detail": "all waits are on conditions" if not sleepers else f"fixed-delay waits in: {sleepers} — a sleep is a bet that CI is as fast as your laptop, and CI loses it",
        }
    )

    with FixtureSite() as site:
        # 4. fixture_serves
        try:
            with urllib.request.urlopen(f"{site.base_url}/", timeout=10) as response:
                body = response.read().decode("utf-8", "replace")
            served = response.status == 200 and "Fixture site" in body
            detail = f"{site.base_url} -> {response.status}"
        except Exception as exc:
            served, detail = False, f"{type(exc).__name__}: {exc}"
        checks.append({"name": "fixture_serves", "ok": served, "detail": detail})

        if not served:
            return {"status": "fail", "checks": checks}

        # 5. workflows_pass
        failures, assertion_total = [], 0
        for path in workflow_files:
            result = run_workflow(path, site.base_url)
            assertion_total += result.assertions
            if not result.ok:
                bad = [s for s in result.steps if not s.ok]
                failures.append(f"{result.workflow}: step {bad[0].index} ({bad[0].action}) {bad[0].detail[:90]}" if bad else f"{result.workflow}: no steps ran")
        checks.append(
            {
                "name": "workflows_pass",
                "ok": not failures,
                "detail": f"{len(workflow_files)} workflow(s) passed, {assertion_total} assertion(s)" if not failures else "; ".join(failures[:3]),
            }
        )

        # 6. detects_breakage — a harness that cannot fail proves nothing.
        broken = {
            "name": "deliberately-broken",
            "steps": [
                {"action": "goto", "url": "/"},
                {"action": "assert_visible", "selector": "#definitely-not-here", "timeout_ms": 1500},
            ],
        }
        broken_path = PROJECT_ROOT / "artifacts" / "_broken.json"
        broken_path.parent.mkdir(parents=True, exist_ok=True)
        broken_path.write_text(json.dumps(broken), encoding="utf-8")
        broken_result = run_workflow(broken_path, site.base_url)
        checks.append(
            {
                "name": "detects_breakage",
                "ok": not broken_result.ok,
                "detail": "a missing selector correctly fails the run"
                if not broken_result.ok
                else "a workflow targeting a nonexistent selector PASSED — the harness cannot detect breakage, so none of its green results mean anything",
            }
        )

        # 8. artifacts_on_fail — piggybacks on the failure just produced.
        checks.append(
            {
                "name": "artifacts_on_fail",
                "ok": bool(broken_result.artifacts),
                "detail": f"captured {broken_result.artifacts}"
                if broken_result.artifacts
                else "a failing step left no screenshot or HTML — CI browser failures rarely reproduce locally, and without artifacts the only tool left is guessing",
            }
        )
        broken_path.unlink(missing_ok=True)

        # 7. deterministic — flake is the defining failure of this shape.
        primary = workflow_files[0]
        outcomes = [run_workflow(primary, site.base_url).ok for _ in range(max(2, repeats))]
        checks.append(
            {
                "name": "deterministic",
                "ok": len(set(outcomes)) == 1 and outcomes[0],
                "detail": f"{primary.stem} ran {len(outcomes)}x -> {outcomes}" + ("" if len(set(outcomes)) == 1 else " — flaky: same input, different result"),
            }
        )

    return {"status": "ok" if all(c["ok"] for c in checks) else "fail", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the browser workflows")
    parser.add_argument("--repeats", type=int, default=3, help="runs for the flake check")
    args = parser.parse_args()

    _t = time.monotonic()
    result = run(args.repeats)
    elapsed = int((time.monotonic() - _t) * 1000)

    print(json.dumps(result, indent=2))
    print(
        f"[<name>-perf] phase=qa_check duration_ms={elapsed} checks={len(result['checks'])} status={result['status']}",
        file=sys.stderr,
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
