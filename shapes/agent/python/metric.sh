#!/usr/bin/env bash
# metric.sh for <name> (shape: agent).
#
# Prints the offline qa_check pass ratio — graph structure, tool wiring,
# scenario replay, termination. Deliberately NOT the live-model pass rate:
# metric.sh is called often (autoresearch, KPI collection) and a metric that
# bills per invocation gets switched off.
#
# For live-model quality, run `make evaluate` and read
# eval/reports/latest.json, or point this at summary.pass_rate once you are
# happy to pay for every measurement.
#
# Contract (AGENTS.md §18): one float on the last line of stdout, logs to stderr.
set -euo pipefail
cd "$(dirname "$0")"

QA_OUTPUT="$(mktemp "${TMPDIR:-/tmp}/<name>-qa-check.XXXXXX")"
trap 'rm -f "$QA_OUTPUT"' EXIT
export QA_OUTPUT

python3 qa_check.py >"$QA_OUTPUT" 2>/dev/null || true

python3 - <<'PY'
import json
import os
try:
    data = json.load(open(os.environ["QA_OUTPUT"]))
    checks = data.get("checks", [])
    print(sum(1 for c in checks if c.get("ok")) / len(checks) if checks else 0.0)
except Exception:
    print(0.0)
PY
