"""E2E check for <name> (shape: backtest).

Verifies that backtest.py produced the expected outputs and the metrics file
has the required schema.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, ClassVar


class Checker:
    name = "<name>"

    REQUIRED_KEYS: ClassVar[set[str]] = {
        "success",
        "trades_count",
        "win_rate",
        "total_return_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
    }
    REQUIRED_OUTPUTS: ClassVar[list[str]] = [
        "results/metrics.json",
        "results/trades.csv",
        "outputs/equity_curve.png",
        "outputs/drawdown.png",
        "outputs/trade_log.xlsx",
    ]

    def run(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        results: dict[str, Any] = {"checks": checks, "status": "ok"}

        # 1. All expected files present and non-empty
        for rel in self.REQUIRED_OUTPUTS:
            p = Path(rel)
            if not p.exists():
                checks.append({"name": f"file_{p.name}", "ok": False, "error": "missing"})
                results["status"] = "fail"
                continue
            if p.stat().st_size == 0:
                checks.append({"name": f"file_{p.name}", "ok": False, "error": "empty"})
                results["status"] = "fail"
                continue
            checks.append(
                {
                    "name": f"file_{p.name}",
                    "ok": True,
                    "size_bytes": p.stat().st_size,
                }
            )

        # 2. metrics.json has the required schema
        metrics_path = Path("results/metrics.json")
        if metrics_path.exists():
            try:
                metrics = json.loads(metrics_path.read_text())
                missing = self.REQUIRED_KEYS - set(metrics.keys())
                ok = not missing
                checks.append(
                    {
                        "name": "metrics_schema",
                        "ok": ok,
                        "missing_keys": sorted(missing) if missing else [],
                        "win_rate": metrics.get("win_rate"),
                        "trades": metrics.get("trades_count"),
                    }
                )
                if not ok:
                    results["status"] = "fail"

                # 3. Sanity checks on metric values
                if metrics.get("trades_count", 0) <= 0:
                    checks.append(
                        {
                            "name": "metrics_sanity",
                            "ok": False,
                            "error": "zero trades — strategy generated no signals",
                        }
                    )
                    results["status"] = "fail"
                else:
                    checks.append({"name": "metrics_sanity", "ok": True})
            except Exception as exc:
                checks.append({"name": "metrics_schema", "ok": False, "error": str(exc)})
                results["status"] = "fail"

        return results


CHECKER_CLASS = Checker


if __name__ == "__main__":
    result = Checker().run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
