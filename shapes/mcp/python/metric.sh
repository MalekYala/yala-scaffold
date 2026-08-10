#!/usr/bin/env bash
# metric.sh for <name> (shape: mcp).
#
# Prints the fraction of qa_check contract checks passing. Replace it with
# something task-specific once the server does real work — tool success rate
# under load, p95 call latency, cache hit ratio.
#
# Contract (AGENTS.md §18):
#   - Exactly one float on the last line of stdout.
#   - All logging to stderr.
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
