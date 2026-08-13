#!/usr/bin/env bash
# metric.sh for <name> (shape: backtest).
#
# The autoresearch loop iterates on config/strategy.yml to maximize this
# metric. Default: win_rate. Change to sharpe_ratio or total_return_pct if
# that's what matters more for your strategy.
#
# Contract: exactly one float on the last line of stdout; logs to stderr.
set -euo pipefail
cd "$(dirname "$0")"

METRIC_NAME="${METRIC_NAME:-win_rate}"

if [ ! -f results/metrics.json ]; then
  # Run the backtest first
  python3 backtest.py 1>&2
fi

if [ ! -f results/metrics.json ]; then
  echo "backtest did not produce results/metrics.json" >&2
  echo 0.0
  exit 0
fi

python3 - <<PY
import json, sys
try:
    data = json.load(open("results/metrics.json"))
    if not data.get("success"):
        print(0.0); sys.exit(0)
    print(float(data.get("$METRIC_NAME", 0.0)))
except Exception as e:
    print(0.0, file=sys.stderr)
    print(0.0)
PY
