"""Multi-stage ETL pipeline for <name>.

Shape: pipeline — orchestrates stages/*.py in numeric order. Each stage:
    - reads its input from state/<previous_stage>/ (or fixtures/ for stage 01)
    - writes its output to state/<this_stage>/
    - is idempotent (AGENTS.md §12): safe to rerun without corrupting state

The final stage writes to outputs/ in addition to state/. outputs/manifest.json
is the success sentinel.

Stage contract:
    Each stage module exposes a `run(ctx: dict) -> dict` function.
    The returned dict is passed to the next stage as `ctx['prev']`.

Run locally:
    python3 pipeline.py
Run a single stage:
    python3 pipeline.py --stage 02
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "info").upper()
STAGES_DIR: Path = Path("stages")
STATE_DIR: Path = Path(os.environ.get("STATE_DIR", "state"))
OUTPUTS_DIR: Path = Path(os.environ.get("OUTPUTS_DIR", "outputs"))
FIXTURES_DIR: Path = Path(os.environ.get("FIXTURES_DIR", "fixtures"))
DATA_DIR: Path = Path(os.environ.get("DATA_DIR", "data"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>")


def discover_stages() -> list[Path]:
    """Return stage files in numeric/alphabetic order (01_*.py, 02_*.py, ...)."""
    return sorted(STAGES_DIR.glob("[0-9][0-9]_*.py"))


def load_stage_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load stage module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_pipeline(only_stage: str | None = None) -> None:
    _t_total = time.monotonic()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    stages = discover_stages()
    if not stages:
        log.error(f"no stages found in {STAGES_DIR}/ (expected 01_*.py, 02_*.py, ...)")
        sys.exit(1)

    if only_stage:
        stages = [s for s in stages if s.stem.startswith(only_stage)]
        if not stages:
            log.error(f"no stage matches prefix {only_stage}")
            sys.exit(1)

    prev_output: dict[str, Any] = {}
    for stage_path in stages:
        stage_name = stage_path.stem
        log.info(f"[<name>-perf] phase=stage_{stage_name} status=starting")
        stage_state_dir = STATE_DIR / stage_name
        stage_state_dir.mkdir(parents=True, exist_ok=True)

        ctx: dict[str, Any] = {
            "stage_name": stage_name,
            "state_dir": stage_state_dir,
            "fixtures_dir": FIXTURES_DIR,
            "data_dir": DATA_DIR,
            "outputs_dir": OUTPUTS_DIR,
            "prev": prev_output,
        }

        _t = time.monotonic()
        try:
            mod = load_stage_module(stage_path)
            prev_output = mod.run(ctx) or {}
        except Exception as exc:
            log.exception(f"stage {stage_name} failed: {exc}")
            sys.exit(1)
        elapsed = int((time.monotonic() - _t) * 1000)
        log.info(f"[<name>-perf] phase=stage_{stage_name} duration_ms={elapsed} status=ok")

        # Persist stage output so re-runs and single-stage runs can pick up
        (stage_state_dir / "output.json").write_text(json.dumps(prev_output, indent=2, default=str))

    # Final success sentinel
    (OUTPUTS_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "success": True,
                "timestamp": int(time.time()),
                "stages_run": [s.stem for s in stages],
                "final_output": prev_output,
            },
            indent=2,
            default=str,
        )
    )
    log.info(f"[<name>-perf] phase=total duration_ms={int((time.monotonic() - _t_total) * 1000)} status=ok stages={len(stages)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the <name> ETL pipeline")
    ap.add_argument("--stage", help="Only run stages matching this prefix (e.g. '02')")
    args = ap.parse_args()
    run_pipeline(only_stage=args.stage)


if __name__ == "__main__":
    main()
