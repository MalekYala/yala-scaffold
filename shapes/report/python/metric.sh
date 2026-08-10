#!/usr/bin/env bash
# metric.sh for <name> (shape: report).
# Prints qa_check.py pass ratio as the default autoresearch metric.
# For content iteration projects (book/essay/blog), replace with a readability
# score, word count target, LLM-judge rating, etc.
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
    print(sum(1 for c in checks if c.get("ok")) / max(len(checks), 1))
except Exception:
    print(0.0)
PY
