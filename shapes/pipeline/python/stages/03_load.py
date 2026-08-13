"""Stage 03 — Load.

Reads state/02_transform/clean.parquet and writes the final artifact to
outputs/final.parquet. This is the last stage; downstream consumers read
from outputs/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run(ctx: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd

    prev = ctx["prev"]
    outputs_dir: Path = ctx["outputs_dir"]

    df = pd.read_parquet(prev["output"])
    dest = outputs_dir / "final.parquet"
    df.to_parquet(dest)

    # Also write a small CSV preview for humans/CI to eyeball
    (outputs_dir / "final_preview.csv").write_text(df.head(50).to_csv(index=False))

    return {
        "source": prev["output"],
        "output": str(dest),
        "row_count": len(df),
        "columns": list(df.columns),
    }
