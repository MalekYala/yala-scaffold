#!/usr/bin/env bash
# metric.sh for <name> (shape: worker).
# Prints jobs_completed_per_min as the headline autoresearch metric.
set -euo pipefail
cd "$(dirname "$0")"

# Count successful phase=process entries in the last minute of logs.
# Falls back to qa_check pass-ratio if there are no logs yet.
if [ -f logs/worker.log ]; then
  python3 - <<'PY'
import re, time, os
cutoff = time.time() - 60
count = 0
try:
    for line in open("logs/worker.log"):
        if "phase=process" in line and "status=ok" in line:
            count += 1
    print(float(count))
except Exception:
    print(0.0)
PY
else
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
    print(sum(1 for c in checks if c.get("ok")) / max(len(checks), 1))
except Exception:
    print(0.0)
PY
fi
