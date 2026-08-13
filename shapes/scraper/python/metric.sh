#!/usr/bin/env bash
# metric.sh for <name> (shape: scraper).
#
# Prints the qa_check pass ratio by default. Once the scraper does real work,
# a better metric is usually extraction *completeness*: the fraction of records
# with every required field populated. That number degrades gradually as a site
# changes, which is exactly the early warning you want.
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
