#!/usr/bin/env bash
# metric.sh for <name> (shape: notebook).
# Prints the fraction of notebooks that execute cleanly.
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
    checks = [c for c in data.get("checks", []) if c.get("name", "").startswith("notebook_")]
    if not checks:
        print(0.0)
    else:
        print(sum(1 for c in checks if c.get("ok")) / len(checks))
except Exception:
    print(0.0)
PY
