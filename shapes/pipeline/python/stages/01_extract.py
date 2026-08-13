"""Stage 01 — Extract.

Reads raw input from fixtures/ (for CI) or data/ (for production) and writes
a normalized intermediate representation to state/01_extract/.

Contract: exposes a single `run(ctx: dict) -> dict` function that returns a
dict summarizing what this stage produced. That dict is passed to stage 02.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run(ctx: dict[str, Any]) -> dict[str, Any]:
    data_dir: Path = ctx["data_dir"]
    fixtures_dir: Path = ctx["fixtures_dir"]
    state_dir: Path = ctx["state_dir"]

    # Prefer real data, fall back to fixtures so CI works offline
    for base in (data_dir, fixtures_dir):
        src = base / "input.csv"
        if src.exists():
            break
    else:
        raise FileNotFoundError(f"no input.csv in {data_dir} or {fixtures_dir}")

    # Persist the raw input verbatim as the stage output
    dest = state_dir / "raw.csv"
    dest.write_bytes(src.read_bytes())

    rows = sum(1 for _ in dest.open()) - 1  # naive row count
    return {"source": str(src), "output": str(dest), "row_count": rows}
