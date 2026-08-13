#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
output="$(mktemp "${TMPDIR:-/tmp}/<name>-qa.XXXXXX")"
trap 'rm -f "$output"' EXIT
python3 qa_check.py >"$output" 2>&1 || true
python3 - "$output" <<'PY'
import json
import sys

try:
    with open(sys.argv[1]) as handle:
        checks = json.load(handle).get("checks", [])
    print(sum(bool(check.get("ok")) for check in checks) / len(checks) if checks else 0.0)
except (OSError, ValueError):
    print(0.0)
PY
