#!/usr/bin/env bash
# metric.sh for <name> (shape: game).
#
# Prints the fraction of headless contract checks passing. Replace it with
# whatever "better" means for your game once you have one — average frame time
# under a benchmark load, a bot's win rate against a fixed opponent, level
# completion rate in a scripted playthrough.
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
