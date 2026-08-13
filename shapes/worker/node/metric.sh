#!/usr/bin/env sh
# metric.sh for <name> (shape: worker, lang: node).
# Prints jobs_completed_per_min as the headline autoresearch metric,
# falling back to qa_check.js pass-ratio if no logs yet.
set -eu
cd "$(dirname "$0")"

if [ -f logs/worker.log ]; then
  node -e '
    const fs = require("fs");
    const cutoff = Date.now() - 60_000;
    let count = 0;
    try {
      const lines = fs.readFileSync("logs/worker.log", "utf8").split("\n");
      for (const line of lines) {
        if (line.includes("phase=process") && line.includes("status=ok")) count += 1;
      }
      console.log(count.toFixed(1));
    } catch (e) { console.log(0.0); }
  '
else
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
fi
