#!/usr/bin/env python3
"""Compare <name>'s current benchmarks against the committed baseline.

Reads `bench/baseline/*.json` and `bench/current/*.json` (the schema
`scripts/bench_run.py` emits), reports the delta per benchmark, and writes a
dated report to `bench/reports/`.

**This command always exits 0.** A regression prints a `⚠ WARN` line and sets
`"regression": true` in the JSON, but never fails the build. Benchmark timings
on shared CI runners are noisy enough that a hard gate would fire on unrelated
load within a week, and a check that cries wolf gets deleted. Gate on the JSON
in a deliberate, separately-tuned job if you want enforcement — but decide that
on purpose, with real variance data, rather than inheriting it by default.

The default threshold is **+10% p50**, not zero, for the same reason: ordinary
run-to-run jitter on a loaded machine is a few percent, and warning on that
trains everyone to ignore the output. Lower it once you have measured your own
variance and know what a real signal looks like.

Usage:
    python3 scripts/bench_compare.py
    python3 scripts/bench_compare.py --baseline bench/baseline --current bench/current
    python3 scripts/bench_compare.py --out bench/reports
    python3 scripts/bench_compare.py --threshold 25   # only warn above +25%

Exit code: always 0, except 2 for a usage/IO error.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = PROJECT_ROOT / "bench" / "baseline"
DEFAULT_CURRENT = PROJECT_ROOT / "bench" / "current"
DEFAULT_REPORTS = PROJECT_ROOT / "bench" / "reports"

TRACKED = ("min_ms", "p50_ms", "p95_ms", "max_ms", "mean_ms")


def load_dir(path: Path) -> dict[str, dict]:
    """Load every *.json in a directory, keyed by benchmark name."""
    results: dict[str, dict] = {}
    if not path.is_dir():
        return results
    for file in sorted(path.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"WARN: skipping {file.name}: {exc}", file=sys.stderr)
            continue
        results[data.get("benchmark", file.stem)] = data
    return results


def delta(baseline: dict, current: dict) -> dict[str, float]:
    """Absolute and percentage change for every tracked statistic."""
    out: dict[str, float] = {}
    for key in TRACKED:
        before = float(baseline.get(key, 0.0))
        after = float(current.get(key, 0.0))
        out[key] = round(after - before, 4)
        out[f"{key.removesuffix('_ms')}_pct"] = (
            round((after - before) / before * 100.0, 2) if before else 0.0
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare benchmarks against a baseline")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument(
        "--threshold",
        type=float,
        default=10.0,
        help="p50 percentage increase above which to warn (default 10)",
    )
    args = parser.parse_args()

    baseline = load_dir(args.baseline)
    current = load_dir(args.current)

    if not current:
        print(
            f"no current results in {args.current} — run `make bench` first",
            file=sys.stderr,
        )
        return 2

    if not baseline:
        print(
            f"no baseline in {args.baseline} — capture one with:\n"
            f"  python3 scripts/bench_run.py --out {args.baseline}\n"
            f"then commit it, so future runs have something to compare against.",
            file=sys.stderr,
        )
        return 2

    entries = []
    regressions = 0

    header = f"{'benchmark':<22} {'baseline':>12} {'current':>12} {'delta':>12}"
    print(header)
    print("-" * len(header))

    for name in sorted(current):
        if name not in baseline:
            print(f"{name:<22} {'—':>12} {current[name]['stats']['p50_ms']:>12.4f}   (new)")
            continue

        before_stats = baseline[name]["stats"]
        after_stats = current[name]["stats"]
        changes = delta(before_stats, after_stats)
        regressed = changes["p50_pct"] > args.threshold

        marker = "  ⚠ WARN" if regressed else ""
        print(
            f"{name:<22} {before_stats['p50_ms']:>12.4f} {after_stats['p50_ms']:>12.4f} "
            f"{changes['p50_pct']:>11.2f}%{marker}"
        )

        if regressed:
            regressions += 1

        entries.append(
            {
                "name": name,
                "baseline": before_stats,
                "current": after_stats,
                "delta": changes,
                "regression": regressed,
            }
        )

    for name in sorted(set(baseline) - set(current)):
        print(f"{name:<22} {baseline[name]['stats']['p50_ms']:>12.4f} {'—':>12}   (missing)")

    report = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "threshold_pct": args.threshold,
        "regressions": regressions,
        "benchmarks": entries,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = _dt.date.today().isoformat()
    destination = args.out / f"bench-compare-{stamp}.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"report: {destination.relative_to(PROJECT_ROOT)}")
    if regressions:
        print(
            f"{regressions} regression(s) above +{args.threshold}% p50 — reported, "
            f"not enforced (see the module docstring for why)."
        )
    else:
        print("no regressions")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
