#!/usr/bin/env python3
"""Portable KPI collector for <name>.

Reads kpi.json from the project root, evaluates each KPI's source, and writes
results to a JSONL file (default: data/kpis.jsonl). Optionally exports to
Prometheus textfile format or pushes to a SaaS dashboard.

This is a self-contained reference implementation. It has no host dependencies
beyond Python 3.10+ and httpx. See docs/KPI_SETUP.md for details on how to
wire it into your monitoring stack.

Usage:
    python3 scripts/kpi_collector.py                       # daemon, every 60s, JSONL output
    python3 scripts/kpi_collector.py --once                # one collection cycle then exit
    python3 scripts/kpi_collector.py --format prometheus --output /var/lib/node_exporter/textfile_collector/<name>.prom
    python3 scripts/kpi_collector.py --format datadog --api-key $DD_API_KEY
"""

import argparse
import json
import logging
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx

DEFAULT_KPI_FILE = "kpi.json"
DEFAULT_OUTPUT = "data/kpis.jsonl"
DEFAULT_INTERVAL = 60
HTTP_TIMEOUT = 5
SHELL_TIMEOUT = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [kpi-collector] %(levelname)s %(message)s",
)
log = logging.getLogger("kpi-collector")

_last_recorded: dict[str, float] = {}


# ── Source evaluators ──────────────────────────────────────────────────────


def eval_http_status(src: dict) -> tuple[float, dict]:
    url = src["url"]
    expect = src.get("expect_status", 200)
    try:
        r = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=False)
        return (1.0 if r.status_code == expect else 0.0, {"status": r.status_code})
    except Exception as exc:
        return (0.0, {"error": str(exc)[:100]})


def eval_http_latency(src: dict) -> tuple[float, dict]:
    url = src["url"]
    try:
        _t = time.monotonic()
        r = httpx.get(url, timeout=HTTP_TIMEOUT)
        ms = (time.monotonic() - _t) * 1000
        return (ms, {"status": r.status_code})
    except Exception as exc:
        return (0.0, {"error": str(exc)[:100]})


def eval_http_json(src: dict) -> tuple[float, dict]:
    url = src["url"]
    field = src.get("field", "value")
    try:
        r = httpx.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for part in field.split("."):
            if isinstance(data, dict):
                data = data.get(part)
            else:
                return (0.0, {"error": f"path miss at {part}"})
        try:
            return (float(data), {})
        except (TypeError, ValueError):
            return (0.0, {"error": f"non-numeric: {data}"})
    except Exception as exc:
        return (0.0, {"error": str(exc)[:100]})


def eval_shell(src: dict, project_dir: Path) -> tuple[float, dict]:
    cmd = src["cmd"]
    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=src.get("timeout_s", SHELL_TIMEOUT),
        )
        for line in reversed(result.stdout.strip().splitlines()):
            line = line.strip()
            try:
                return (float(line), {"exit_code": result.returncode})
            except ValueError:
                continue
        return (0.0, {"error": "no numeric output", "exit_code": result.returncode})
    except subprocess.TimeoutExpired:
        return (0.0, {"error": "timeout"})
    except Exception as exc:
        return (0.0, {"error": str(exc)[:100]})


def eval_metric_log_grep(src: dict, project_dir: Path) -> tuple[float, dict]:
    log_path = Path(src["log_file"])
    if not log_path.is_absolute():
        log_path = project_dir / log_path
    pattern = src["pattern"]
    window_s = src.get("window_s", 60)
    aggregate = src.get("aggregate", "count")

    if not log_path.exists():
        return (0.0, {"error": "log not found"})

    matches = 0
    values: list[float] = []
    try:
        with log_path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            text = f.read().decode("utf-8", errors="replace")
        compiled = re.compile(pattern)
        for line in text.splitlines():
            m = compiled.search(line)
            if not m:
                continue
            matches += 1
            if m.groups():
                try:
                    values.append(float(m.group(1)))
                except (ValueError, IndexError):
                    pass
    except Exception as exc:
        return (0.0, {"error": str(exc)[:100]})

    if aggregate == "count":
        return (float(matches), {"matches": matches})
    if not values:
        return (0.0, {"matches": matches})
    if aggregate == "sum":
        return (sum(values), {"n": len(values)})
    if aggregate == "mean":
        return (statistics.mean(values), {"n": len(values)})
    if aggregate == "max":
        return (max(values), {"n": len(values)})
    if aggregate.startswith("p"):
        try:
            pct = int(aggregate[1:]) / 100
            sorted_vals = sorted(values)
            idx = min(int(pct * len(sorted_vals)), len(sorted_vals) - 1)
            return (sorted_vals[idx], {"n": len(values)})
        except ValueError:
            return (0.0, {"error": f"bad aggregate: {aggregate}"})
    return (0.0, {"error": f"unknown aggregate: {aggregate}"})


def eval_sql(src: dict) -> tuple[float, dict]:
    """Run a Postgres query via psycopg. Requires psycopg installed:
    pip install 'psycopg[binary]'
    """
    try:
        import psycopg
    except ImportError:
        return (0.0, {"error": "psycopg not installed (pip install 'psycopg[binary]')"})
    db_url = src.get("dsn") or os.environ.get("DATABASE_URL")
    if not db_url and "db" in src:
        # Build a connection string from individual fields
        db_url = f"postgresql://{src.get('user', 'postgres')}:{src.get('password', '')}@{src.get('host', 'localhost')}:{src.get('port', 5432)}/{src['db']}"
    if not db_url:
        return (0.0, {"error": "no db connection info"})
    try:
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(src["query"])
                row = cur.fetchone()
                if row is None:
                    return (0.0, {"error": "empty result"})
                return (float(row[0]), {})
    except Exception as exc:
        return (0.0, {"error": str(exc)[:100]})


def eval_static(src: dict) -> tuple[float, dict]:
    return (float(src.get("value", 0)), {})


SOURCE_EVALUATORS = {
    "http_status": lambda s, p: eval_http_status(s),
    "http_latency": lambda s, p: eval_http_latency(s),
    "http_json": lambda s, p: eval_http_json(s),
    "shell": lambda s, p: eval_shell(s, p),
    "metric_log_grep": lambda s, p: eval_metric_log_grep(s, p),
    "sql": lambda s, p: eval_sql(s),
    "static": lambda s, p: eval_static(s),
}


def evaluate_kpi(kpi: dict, project_dir: Path) -> tuple[float | None, dict]:
    src = kpi.get("source", {})
    src_type = src.get("type")
    fn = SOURCE_EVALUATORS.get(src_type)
    if not fn:
        return (None, {"error": f"unknown source type: {src_type}"})
    try:
        return fn(src, project_dir)
    except Exception as exc:
        return (None, {"error": str(exc)[:100]})


# ── Output writers ─────────────────────────────────────────────────────────


def write_jsonl(output_path: Path, project: str, name: str, value: float, metadata: dict, kpi: dict):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": int(time.time()),
        "project": project,
        "name": name,
        "value": value,
        "metadata": metadata,
        "unit": kpi.get("unit"),
        "direction": kpi.get("direction"),
        "target": kpi.get("target"),
    }
    with output_path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def write_prometheus(output_path: Path, project: str, kpis_collected: list[tuple[dict, float, dict]]):
    """Atomically write a .prom file in the textfile collector format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    safe_project = re.sub(r"[^a-zA-Z0-9_]", "_", project)
    for kpi, value, _meta in kpis_collected:
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", kpi["name"])
        metric = f"{safe_project}_{safe_name}"
        desc = (kpi.get("description") or "").replace("\n", " ").replace("\\", "\\\\")
        kpi_type = kpi.get("kpi_type", "gauge")
        prom_type = "gauge" if kpi_type in ("gauge", "boolean", "float") else "counter"
        lines.append(f"# HELP {metric} {desc}")
        lines.append(f"# TYPE {metric} {prom_type}")
        lines.append(f"{metric} {value}")
    tmp = output_path.with_suffix(".prom.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(output_path)


def push_datadog(api_key: str, project: str, kpis_collected: list[tuple[dict, float, dict]]):
    """Push metrics to Datadog via the v1 series API."""
    now = int(time.time())
    series = []
    for kpi, value, _meta in kpis_collected:
        series.append({
            "metric": f"{project}.{kpi['name']}",
            "points": [[now, value]],
            "type": "gauge",
            "tags": [f"project:{project}", f"unit:{kpi.get('unit', '')}"],
        })
    try:
        r = httpx.post(
            "https://api.datadoghq.com/api/v1/series",
            json={"series": series},
            headers={"DD-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=10,
        )
        if r.status_code >= 300:
            log.warning("datadog push failed: %s %s", r.status_code, r.text[:200])
    except Exception as exc:
        log.warning("datadog push exception: %s", exc)


# ── Main loop ──────────────────────────────────────────────────────────────


def collect_once(kpi_file: Path, args, force_all: bool = False) -> list[tuple[dict, float, dict]]:
    try:
        cfg = json.loads(kpi_file.read_text())
    except Exception as exc:
        log.error("could not parse %s: %s", kpi_file, exc)
        return []

    project = cfg.get("project") or kpi_file.parent.name
    project_dir = kpi_file.parent
    now = time.time()
    collected = []

    for kpi in cfg.get("kpis", []):
        name = kpi.get("name")
        if not name:
            continue
        interval = kpi.get("interval_s", 60)
        if not force_all:
            last = _last_recorded.get(name, 0)
            if now - last < interval:
                continue

        value, meta = evaluate_kpi(kpi, project_dir)
        if value is None:
            log.debug("skip %s: %s", name, meta)
            continue

        collected.append((kpi, value, meta))
        _last_recorded[name] = now

        if args.format == "jsonl":
            write_jsonl(Path(args.output), project, name, value, meta, kpi)
        log.info("collected %s = %s", name, value)

    if collected:
        if args.format == "prometheus":
            write_prometheus(Path(args.output), project, collected)
        elif args.format == "datadog":
            if not args.api_key:
                log.error("datadog format requires --api-key (or set DD_API_KEY env var)")
            else:
                push_datadog(args.api_key, project, collected)

    return collected


def main():
    parser = argparse.ArgumentParser(description="Portable KPI collector")
    parser.add_argument("--kpi-file", default=DEFAULT_KPI_FILE, help="Path to kpi.json (default: ./kpi.json)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output path (default: data/kpis.jsonl)")
    parser.add_argument("--format", default="jsonl", choices=["jsonl", "prometheus", "datadog"],
                        help="Output format (default: jsonl)")
    parser.add_argument("--api-key", default=os.environ.get("DD_API_KEY"), help="API key for SaaS formats")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Loop interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    kpi_file = Path(args.kpi_file)
    if not kpi_file.exists():
        log.error("kpi.json not found at %s", kpi_file)
        sys.exit(1)

    log.info("kpi-collector starting (format=%s, interval=%ds, kpi_file=%s)",
             args.format, args.interval, kpi_file)

    while True:
        _t = time.monotonic()
        try:
            collected = collect_once(kpi_file, args, force_all=args.once)
            elapsed = int((time.monotonic() - _t) * 1000)
            log.info("[kpi-collector-perf] phase=loop duration_ms=%d collected=%d",
                     elapsed, len(collected))
        except Exception as exc:
            log.warning("loop error: %s", exc)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("interrupted")
        sys.exit(0)
