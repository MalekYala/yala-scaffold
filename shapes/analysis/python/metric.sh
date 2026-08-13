#!/usr/bin/env bash
# metric.sh for <name> (shape: analysis).
#
# By default prints the qa_check.py pass ratio. Replace with a
# project-specific metric (e.g., model accuracy, anomaly count, agreement
# with a baseline) once your analyze.py produces one.
#
# Contract (AGENTS.md §18):
#   - Exactly one float on the last line of stdout.
#   - All logging to stderr.
set -euo pipefail
cd "$(dirname "$0")"

QA_OUTPUT="$(mktemp "${TMPDIR:-/tmp}/<name>-qa-check.XXXXXX")"
trap 'rm -f "$QA_OUTPUT"' EXIT
export QA_OUTPUT

python3 qa_check.py >"$QA_OUTPUT" 2>&1 || true

python3 - <<'PY'
import json
import os
try:
    data = json.load(open(os.environ["QA_OUTPUT"]))
    checks = data.get("checks", [])
    if not checks:
        print(0.0)
    else:
        print(sum(1 for c in checks if c.get("ok")) / len(checks))
except Exception:
    print(0.0)
PY
