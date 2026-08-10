#!/usr/bin/env bash
# metric.sh for <name> (shape: model).
#
# Prints the primary evaluation metric: exact-match accuracy from the latest
# eval report. This is the number the autoresearch loop optimises — change the
# dataset or a hyperparameter, retrain, re-evaluate, keep or revert.
#
# If your task's real success measure is something else (F1, a per-field
# accuracy, a downstream business metric), change this to print that instead.
# The loop is only as honest as this number: optimising exact match when you
# actually care about one field's recall will confidently move you sideways.
#
# Contract (AGENTS.md §18):
#   - Exactly one float on the last line of stdout.
#   - All logging to stderr.
set -euo pipefail
cd "$(dirname "$0")"

REPORT="${EVAL_REPORT:-eval/reports/latest.json}"

python3 - "$REPORT" <<'PY'
import json
import sys

try:
    with open(sys.argv[1]) as handle:
        report = json.load(handle)
    summary = report.get("summary", {})
    # No scored examples means no information — report 0.0 rather than a
    # flattering vacuum. A metric that reads 1.0 because nothing ran is how an
    # autoresearch loop optimises itself into a corner.
    if not summary.get("scored"):
        print(0.0)
    else:
        print(float(summary.get("exact_match", 0.0)))
except Exception as exc:  # noqa: BLE001
    print(f"metric.sh: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(0.0)
PY
