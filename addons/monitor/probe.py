#!/usr/bin/env python3
"""Scheduled external prober for <name>.

`kpi.json` declares what is worth measuring. `qa_check` answers "does it work"
on demand. Neither of them runs *while nobody is looking* — which is when
things actually break.

This probe closes that gap: run it from cron, a systemd timer, or a CI
schedule, and it checks `/health` plus every HTTP-sourced KPI in `kpi.json`,
appending one JSON line per run to a durable log.

It deliberately does the boring, reliable thing — an append-only JSONL file —
rather than integrating with a metrics backend. Point `--out` at a path your
existing collector already ingests, or post-process it however you like.

Usage:
    python3 monitor/probe.py
    python3 monitor/probe.py --base-url http://127.0.0.1:<PORT>
    python3 monitor/probe.py --out data/probes.jsonl
    python3 monitor/probe.py --once --quiet     # cron-friendly

Cron example (every 5 minutes, quiet unless something fails):

    */5 * * * * cd /path/to/<name> && python3 monitor/probe.py --quiet

Exit codes:
    0  every probe passed
    1  at least one probe failed (so cron mails you, and only then)
    2  configuration error
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KPI_FILE = PROJECT_ROOT / "kpi.json"
DEFAULT_OUT = PROJECT_ROOT / "data" / "probes.jsonl"
DEFAULT_BASE_URL = "http://127.0.0.1:<PORT>"


def probe_http(url: str, timeout: float = 10.0) -> dict[str, object]:
    """One HTTP probe. Never raises — a probe that crashes reports nothing."""
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            body = response.read(65536)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "url": url,
                "ok": 200 <= response.status < 300,
                "status": response.status,
                "latency_ms": round(elapsed_ms, 2),
                "bytes": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {
            "url": url,
            "ok": False,
            "status": exc.code,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001 — a probe must never take the loop down
        return {
            "url": url,
            "ok": False,
            "status": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "error": type(exc).__name__ + ": " + str(exc),
        }


def kpi_urls(base_url: str) -> list[tuple[str, str]]:
    """(kpi_name, url) for every KPI declaring an HTTP source."""
    if not KPI_FILE.is_file():
        return []
    try:
        data = json.loads(KPI_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"WARN: {KPI_FILE.name} is not valid JSON: {exc}", file=sys.stderr)
        return []

    found: list[tuple[str, str]] = []
    for kpi in data.get("kpis", data if isinstance(data, list) else []):
        if not isinstance(kpi, dict):
            continue
        source = kpi.get("source", {})
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            found.append((kpi.get("name", url), url))
        elif isinstance(url, str) and url.startswith("/"):
            found.append((kpi.get("name", url), base_url.rstrip("/") + url))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe this project's health and KPIs")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--quiet", action="store_true", help="print only on failure")
    parser.add_argument("--once", action="store_true", help="accepted for cron readability")
    args = parser.parse_args()

    targets: list[tuple[str, str]] = [("health", args.base_url.rstrip("/") + "/health")]
    targets.extend(kpi_urls(args.base_url))

    results = []
    failed = 0
    for name, url in targets:
        result = probe_http(url, timeout=args.timeout)
        result["name"] = name
        results.append(result)
        if not result["ok"]:
            failed += 1

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": "<name>",
        "probes": results,
        "failed": failed,
    }

    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"ERROR: cannot append to {args.out}: {exc}", file=sys.stderr)
        return 2

    if failed or not args.quiet:
        for result in results:
            marker = "ok  " if result["ok"] else "FAIL"
            detail = result.get("error", f"HTTP {result['status']}")
            print(f"{marker} {result['name']:<24} {result['latency_ms']:>8.2f}ms  {detail}")
        print(f"[<name>-perf] phase=probe duration_ms={sum(r['latency_ms'] for r in results):.0f} probes={len(results)} failed={failed}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
