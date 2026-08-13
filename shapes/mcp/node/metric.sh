#!/usr/bin/env bash
# metric.sh for <name> (shape: mcp, lang: node).
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

node qa_check.js >"$QA_OUTPUT" 2>/dev/null || true

QA_OUTPUT="$QA_OUTPUT" node -e '
  try {
    const fs = require("fs");
    const data = JSON.parse(fs.readFileSync(process.env.QA_OUTPUT, "utf8"));
    const checks = data.checks || [];
    if (checks.length === 0) { console.log(0.0); process.exit(0); }
    const passed = checks.filter(c => c.ok).length;
    console.log((passed / checks.length).toFixed(4));
  } catch (e) {
    console.log(0.0);
  }
'
