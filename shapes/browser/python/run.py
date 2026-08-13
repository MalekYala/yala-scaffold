"""Entry point for <name> (shape: browser).

    python3 run.py                     # every workflow, against the fixture site
    python3 run.py --workflow search   # just one
    python3 run.py --url https://real.example --headed --trace

With no --url it serves the committed fixture site on an ephemeral port, so a
fresh clone runs end to end with nothing external configured.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import config
from fixtures.server import FixtureSite
from runner import run_workflow

settings = config.load()
PROJECT_ROOT = Path(__file__).resolve().parent

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("<name>")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run browser workflows")
    parser.add_argument("--workflow", help="run only this workflow (by file stem)")
    parser.add_argument("--url", default=settings.target_base_url, help="base URL")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--trace", action="store_true", help="capture a trace even on success")
    args = parser.parse_args()

    workflows = sorted((PROJECT_ROOT / "workflows").glob("*.json"))
    if args.workflow:
        workflows = [p for p in workflows if p.stem == args.workflow]
        if not workflows:
            print(f"ERROR: no workflow named {args.workflow!r}", file=sys.stderr)
            return 2
    if not workflows:
        print("ERROR: no workflows in workflows/", file=sys.stderr)
        return 2

    site = None
    base_url = args.url
    if not base_url:
        site = FixtureSite()
        base_url = site.start()
        log.info(f"serving the committed fixture site at {base_url}")

    failed = 0
    _t = time.monotonic()
    try:
        for path in workflows:
            result = run_workflow(
                path,
                base_url,
                headless=not args.headed and settings.headless,
                trace=args.trace or settings.trace,
            )
            mark = "ok  " if result.ok else "FAIL"
            print(f"{mark} {result.workflow:<20} {len(result.steps)} step(s), {result.assertions} assertion(s)")
            for step in result.steps:
                if not step.ok:
                    print(f"       step {step.index} ({step.action}): {step.detail}", file=sys.stderr)
            if result.artifacts:
                print(f"       artifacts: {', '.join(result.artifacts)}", file=sys.stderr)
            failed += 0 if result.ok else 1
    finally:
        if site is not None:
            site.stop()

    elapsed = int((time.monotonic() - _t) * 1000)
    print(f"[<name>-perf] phase=total duration_ms={elapsed} workflows={len(workflows)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
