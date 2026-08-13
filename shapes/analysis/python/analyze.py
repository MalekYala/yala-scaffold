"""One-shot data analysis for <name>.

Shape: analysis — reads input data, performs analysis, writes outputs/ then exits.

Required outputs (checked by qa_check.py and the CI pipeline):
    outputs/summary.json     — machine-readable result summary
    outputs/report.md        — human-readable report
    outputs/*.png            — graphs referenced by the report

The `results/metrics.json` file is written last — if it exists, the run
succeeded. Its presence is the single success signal the rest of the project
uses (metric.sh, KPI collector, CI assertion, autoresearch loop).

Run locally:
    python3 analyze.py

In Docker:
    docker compose up
    # outputs/ is populated on exit
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "info").upper()
OUTPUTS_DIR: Path = Path(os.environ.get("OUTPUTS_DIR", "outputs"))
DATA_DIR: Path = Path(os.environ.get("DATA_DIR", "data"))
FIXTURES_DIR: Path = Path(os.environ.get("FIXTURES_DIR", "fixtures"))
RESULTS_DIR: Path = Path(os.environ.get("RESULTS_DIR", "results"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>")


def load_input() -> pd.DataFrame:
    """Load the input data.

    Loads from DATA_DIR in production and FIXTURES_DIR when data is absent
    (so CI can run without operator-supplied data).
    """
    # Prefer real data, fall back to fixtures for CI / smoke tests
    for path in (DATA_DIR / "input.csv", FIXTURES_DIR / "sample_input.csv"):
        if path.exists():
            log.info(f"loading input from {path}")
            return pd.read_csv(path)
    raise FileNotFoundError(f"no input found in {DATA_DIR}/input.csv or {FIXTURES_DIR}/sample_input.csv")


def analyze(df: pd.DataFrame) -> dict[str, Any]:
    """Run the analysis and return a result summary dict.

    Replace this with your real analysis. The contract is: given a DataFrame,
    return a dict that can be JSON-serialized and is the machine-readable
    result summary.
    """
    # TODO: replace with your real analysis
    summary: dict[str, Any] = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": list(df.columns),
    }
    return summary


def write_outputs(df: pd.DataFrame, summary: dict[str, Any]) -> None:
    """Write all required outputs. This is the only place outputs are created."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # outputs/summary.json — machine-readable summary
    (OUTPUTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    log.info(f"wrote {OUTPUTS_DIR}/summary.json")

    # outputs/report.md — human-readable report
    report = "# <name> — Analysis Report\n\n"
    report += f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n\n"
    report += "## Summary\n\n"
    for k, v in summary.items():
        report += f"- **{k}:** {v}\n"
    report += "\n## Graphs\n\n![Distribution](distribution.png)\n"
    (OUTPUTS_DIR / "report.md").write_text(report)
    log.info(f"wrote {OUTPUTS_DIR}/report.md")

    # outputs/distribution.png — example graph
    if len(df.columns) > 0:
        numeric_cols = df.select_dtypes(include="number").columns
        if len(numeric_cols) > 0:
            fig, ax = plt.subplots(figsize=(8, 5))
            df[numeric_cols[0]].hist(ax=ax, bins=30)
            ax.set_title(f"Distribution of {numeric_cols[0]}")
            fig.tight_layout()
            fig.savefig(OUTPUTS_DIR / "distribution.png", dpi=100)
            plt.close(fig)
            log.info(f"wrote {OUTPUTS_DIR}/distribution.png")

    # results/metrics.json — success sentinel. Written last.
    (RESULTS_DIR / "metrics.json").write_text(
        json.dumps(
            {
                "success": True,
                "timestamp": int(time.time()),
                **summary,
            },
            indent=2,
        )
    )
    log.info(f"wrote {RESULTS_DIR}/metrics.json — run complete")


def main() -> None:
    _t_total = time.monotonic()
    log.info("<name> analysis starting")

    _t = time.monotonic()
    df = load_input()
    log.info(f"[<name>-perf] phase=load duration_ms={int((time.monotonic() - _t) * 1000)} rows={len(df)}")

    _t = time.monotonic()
    summary = analyze(df)
    log.info(f"[<name>-perf] phase=analyze duration_ms={int((time.monotonic() - _t) * 1000)}")

    _t = time.monotonic()
    write_outputs(df, summary)
    log.info(f"[<name>-perf] phase=write duration_ms={int((time.monotonic() - _t) * 1000)}")

    log.info(f"[<name>-perf] phase=total duration_ms={int((time.monotonic() - _t_total) * 1000)} status=ok")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.exception(f"analysis failed: {exc}")
        sys.exit(1)
    sys.exit(0)
