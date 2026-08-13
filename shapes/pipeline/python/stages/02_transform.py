"""Stage 02 — Transform.

Reads state/01_extract/raw.csv, applies cleaning/normalization, writes
state/02_transform/clean.parquet. Replace the stub with real transforms.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run(ctx: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd

    prev = ctx["prev"]
    state_dir: Path = ctx["state_dir"]
    src = Path(prev["output"])

    df = pd.read_csv(src)

    # TODO: real transforms — schema normalization, type casting, dedup, etc.
    df = df.drop_duplicates()

    dest = state_dir / "clean.parquet"
    df.to_parquet(dest)

    return {
        "source": str(src),
        "output": str(dest),
        "row_count_in": int(prev.get("row_count", -1)),
        "row_count_out": len(df),
    }
