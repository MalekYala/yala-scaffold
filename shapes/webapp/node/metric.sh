#!/usr/bin/env sh
# metric.sh for <name> (shape: webapp, lang: node).
# Prints qa_check.js pass ratio.
set -eu
cd "$(dirname "$0")"

QA_OUTPUT="${TMPDIR:-/tmp}/qa_check_output.$$.json"
trap 'rm -f "$QA_OUTPUT"' EXIT
node qa_check.js > "$QA_OUTPUT" 2>&1 || true

QA_OUTPUT="$QA_OUTPUT" node -e '
  try {
    const fs = require("fs");
    const data = JSON.parse(fs.readFileSync(process.env.QA_OUTPUT, "utf8"));
    const checks = data.checks || [];
    if (checks.length === 0) { console.log(0.0); process.exit(0); }
    const passed = checks.filter(c => c.ok).length;
    console.log((passed / checks.length).toFixed(4));
  } catch (e) { console.log(0.0); }
'
