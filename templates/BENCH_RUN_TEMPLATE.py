#!/usr/bin/env python3
"""Run <name>'s declared benchmarks and emit fixed-schema JSON.

`metric.sh` answers "how good is it right now". This answers "is it slower
than it was", which is a different and equally important question — and the one
nothing in a fresh project currently tracks.

Benchmarks are declared as data in `bench/benchmarks.json`:

    {
      "benchmarks": [
        {"name": "startup", "command": "python3 -c 'import app'", "iterations": 20}
      ]
    }

so adding one never means editing this file. Each is run `iterations` times and
reduced to min/p50/p95/max/mean, matching the schema `scripts/bench_compare.py`
expects.

Usage:
    python3 scripts/bench_run.py                     # all, to bench/current/
    python3 scripts/bench_run.py --name startup      # just one
    python3 scripts/bench_run.py --out bench/baseline # capture a new baseline
    python3 scripts/bench_run.py --iterations 5      # override the declared count

Exit codes:
    0  every benchmark ran
    1  a benchmark command failed
    2  no benchmark declarations found
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECLARATIONS = PROJECT_ROOT / "bench" / "benchmarks.json"
DEFAULT_OUT = PROJECT_ROOT / "bench" / "current"


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile. Small sample sizes make interpolation a lie."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * len(ordered) + 0.5)) - 1))
    return ordered[index]


def command_succeeds(command: str) -> bool:
    """One untimed probe: can this benchmark run at all right now?"""
    return (
        subprocess.run(command, shell=True, cwd=PROJECT_ROOT, capture_output=True).returncode
        == 0
    )


def run_one(name: str, command: str, iterations: int) -> dict[str, object]:
    """Time a command `iterations` times, discarding a warmup run."""
    samples: list[float] = []

    # One untimed warmup: the first run pays for cold caches, imports and page
    # faults, and including it makes p50 depend on how recently you ran it.
    subprocess.run(command, shell=True, cwd=PROJECT_ROOT, capture_output=True)

    for _ in range(iterations):
        started = time.perf_counter()
        result = subprocess.run(command, shell=True, cwd=PROJECT_ROOT, capture_output=True)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if result.returncode != 0:
            raise RuntimeError(
                f"benchmark {name!r} command failed (exit {result.returncode}):\n"
                f"  {command}\n{result.stderr.decode('utf-8', 'replace').strip()}"
            )
        samples.append(elapsed_ms)

    return {
        "benchmark": name,
        "version": os.environ.get("APP_VERSION", "0.0.0-dev"),
        "python_version": platform.python_version(),
        "os": platform.system().lower(),
        "arch": platform.machine(),
        "stats": {
            "iterations": len(samples),
            "min_ms": round(min(samples), 4),
            "p50_ms": round(percentile(samples, 0.50), 4),
            "p95_ms": round(percentile(samples, 0.95), 4),
            "max_ms": round(max(samples), 4),
            "mean_ms": round(statistics.fmean(samples), 4),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run declared benchmarks")
    parser.add_argument("--name", help="run only this benchmark")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    parser.add_argument("--iterations", type=int, help="override the declared iteration count")
    args = parser.parse_args()

    if not DECLARATIONS.is_file():
        print(f"ERROR: no benchmark declarations at {DECLARATIONS}", file=sys.stderr)
        return 2

    declared = json.loads(DECLARATIONS.read_text(encoding="utf-8")).get("benchmarks", [])
    if args.name:
        declared = [b for b in declared if b.get("name") == args.name]
        if not declared:
            print(f"ERROR: no benchmark named {args.name!r}", file=sys.stderr)
            return 2
    if not declared:
        print(f"no benchmarks declared in {DECLARATIONS.name} — nothing to run")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)

    completed = 0
    skipped: list[str] = []

    for spec in declared:
        name = spec["name"]
        iterations = args.iterations or int(spec.get("iterations", 20))

        # A benchmark that needs the service up is not a failure when it is
        # down — that is just the wrong moment to measure. Skip it loudly and
        # write no result file, so bench_compare reports it as missing rather
        # than quietly comparing nothing and calling that success.
        if spec.get("requires_running") and not command_succeeds(spec["command"]):
            reason = spec.get("requires_hint", "is the service running? try `make run`")
            print(f"skipping {name} — {reason}", file=sys.stderr)
            skipped.append(name)
            continue

        print(f"running {name} ({iterations} iterations)…", file=sys.stderr)
        try:
            result = run_one(name, spec["command"], iterations)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        destination = args.out / f"{name}.json"
        destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        stats = result["stats"]
        completed += 1
        print(
            f"[<name>-perf] phase=bench_{name} duration_ms={stats['p50_ms']} "
            f"iterations={stats['iterations']} p95_ms={stats['p95_ms']}"
        )

    print(f"wrote {completed} result(s) to {args.out}", file=sys.stderr)
    if skipped:
        print(f"skipped: {', '.join(skipped)}", file=sys.stderr)
    if completed == 0:
        print(
            "no benchmark could run — nothing was measured, so nothing is known",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
