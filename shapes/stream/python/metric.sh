#!/usr/bin/env bash
# metric.sh — single-script ground-truth scoring for <name> (shape: stream).
#
# Prints a single float to stdout. That float is the value `make iterate`
# uses to decide whether an autoresearch change is "better". Defaults to
# the pass-ratio of qa_check.py.
#
# Contract (AGENTS.md §18):
#   - MUST print exactly one numeric value as the LAST line of stdout.
#   - All logging goes to stderr.
#   - Exit code 0 on success, non-zero on catastrophic failure (no score).
set -euo pipefail

cd "$(dirname "$0")"

# Run qa_check.py and compute pass ratio
QA_OUTPUT="$(mktemp "${TMPDIR:-/tmp}/<name>-qa-check.XXXXXX")"
trap 'rm -f "$QA_OUTPUT"' EXIT
export QA_OUTPUT

python3 qa_check.py >"$QA_OUTPUT" 2>&1 || true

python3 - <<'PY'
import json
import os
try:
    with open(os.environ["QA_OUTPUT"]) as f:
        data = json.load(f)
    checks = data.get("checks", [])
    if not checks:
        print(0.0)
    else:
        passed = sum(1 for c in checks if c.get("ok"))
        print(passed / len(checks))
except Exception:
    print(0.0)
PY
