#!/usr/bin/env python3
"""End-to-end check for <name> (shape: game).

Thin wrapper: the real work happens in `scripts/qa_check.gd`, which runs inside
Godot headlessly and emits JSON. This finds the engine, runs it, and reports in
the same shape as every other checker in this kit.

Splitting it that way keeps the engine-specific logic in the engine's own
language, where it can use the real scene loader and the real simulation rather
than re-implementing either. Porting the shape to another engine means
rewriting one GDScript file, not this one.

Usage:
    python3 qa_check.py
    python3 qa_check.py --godot /path/to/godot

Exit codes:
    0  every check passed
    1  a check failed
    2  Godot could not be found or did not produce a report
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
CANDIDATES = ("godot", "godot4", "Godot", "/usr/local/bin/godot")


def find_godot(explicit: str | None) -> str | None:
    for candidate in filter(None, (explicit, os.environ.get("GODOT_BIN"), *CANDIDATES)):
        found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            return found
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the headless game contract check")
    parser.add_argument("--godot", help="path to the Godot binary")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    godot = find_godot(args.godot)
    if godot is None:
        print(
            "ERROR: no Godot binary found. Set GODOT_BIN, pass --godot, or use\n       `make qa`, which runs this inside the project's container.",
            file=sys.stderr,
        )
        return 2

    _t = time.monotonic()
    # --import first: a fresh clone has no .godot/ cache, and without it Godot
    # resolves neither UIDs nor global class names. Skipping this is why a
    # check can pass locally and fail on the first CI run.
    subprocess.run(
        [godot, "--headless", "--path", str(PROJECT_ROOT), "--import"],
        capture_output=True,
        timeout=args.timeout,
    )
    result = subprocess.run(
        [godot, "--headless", "--path", str(PROJECT_ROOT), "--script", "scripts/qa_check.gd"],
        capture_output=True,
        text=True,
        timeout=args.timeout,
    )

    report = None
    for line in reversed(result.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                report = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    if report is None:
        print(
            "ERROR: the headless check produced no report — Godot most likely failed to load the project.",
            file=sys.stderr,
        )
        print(result.stdout[-1500:], file=sys.stderr)
        print(result.stderr[-1500:], file=sys.stderr)
        return 2

    elapsed = int((time.monotonic() - _t) * 1000)
    print(json.dumps(report, indent=2))
    print(
        f"[<name>-perf] phase=qa_check duration_ms={elapsed} checks={len(report.get('checks', []))} status={report.get('status')}",
        file=sys.stderr,
    )
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
