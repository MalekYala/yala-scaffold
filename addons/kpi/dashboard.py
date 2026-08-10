#!/usr/bin/env python3
"""Portable KPI dashboard for <name>.

A self-contained FastAPI dashboard that reads data/kpis.jsonl (written by
scripts/kpi_collector.py) and serves an HTML view with sparklines, percentiles,
and target compliance.

Run:
    pip install fastapi uvicorn
    python3 scripts/kpi_dashboard.py
    # Open http://127.0.0.1:9090

Override port via DASHBOARD_PORT env var.
"""

import json
import os
import statistics
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

KPI_DATA_FILE = Path(os.environ.get("KPI_DATA_FILE", "data/kpis.jsonl"))
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "9090"))
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PROJECT = os.environ.get("PROJECT", "<name>")

app = FastAPI(title=f"{PROJECT} KPI Dashboard")


def load_records() -> list[dict]:
    if not KPI_DATA_FILE.exists():
        return []
    records = []
    with KPI_DATA_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def fmt_num(n) -> str:
    if n is None:
        return "—"
    n = float(n)
    if abs(n) >= 1000:
        return f"{n:.0f}"
    if abs(n) >= 1:
        return f"{n:.2f}"
    return f"{n:.4f}"


@app.get("/health")
def health():
    return {"status": "ok", "service": "kpi-dashboard"}


@app.get("/api/kpis")
def api_kpis():
    records = load_records()
    by_name = defaultdict(list)
    for r in records:
        by_name[r["name"]].append(r)

    summary = {}
    for name, recs in by_name.items():
        values = [r["value"] for r in recs]
        latest = recs[-1]
        if values:
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            summary[name] = {
                "latest": latest["value"],
                "min": min(values),
                "max": max(values),
                "mean": statistics.mean(values),
                "p50": sorted_vals[int(0.50 * n)],
                "p95": sorted_vals[min(int(0.95 * n), n - 1)],
                "p99": sorted_vals[min(int(0.99 * n), n - 1)],
                "n": n,
                "unit": latest.get("unit"),
                "target": latest.get("target"),
                "direction": latest.get("direction"),
                "last_ts": latest["ts"],
            }
    return JSONResponse({"project": PROJECT, "kpis": summary})


@app.get("/", response_class=HTMLResponse)
def dashboard():
    records = load_records()
    if not records:
        return HTMLResponse(f"""<!doctype html><html><head><title>{PROJECT} KPIs</title>
<style>body{{font-family:system-ui;max-width:900px;margin:2em auto;padding:0 1em;background:#0d1117;color:#c9d1d9}}</style></head>
<body><h1>{PROJECT} KPIs</h1><p>No data yet. Run <code>python3 scripts/kpi_collector.py --once</code> to collect a sample.</p></body></html>""")

    by_name = defaultdict(list)
    for r in records:
        by_name[r["name"]].append(r)

    cards = []
    for name in sorted(by_name.keys()):
        recs = by_name[name]
        values = [float(r["value"]) for r in recs]
        latest = recs[-1]
        if not values:
            continue

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        stats_data = {
            "min": min(values),
            "max": max(values),
            "mean": statistics.mean(values),
            "p50": sorted_vals[int(0.50 * n)],
            "p95": sorted_vals[min(int(0.95 * n), n - 1)],
            "p99": sorted_vals[min(int(0.99 * n), n - 1)],
            "n": n,
        }

        unit = latest.get("unit", "")
        target = latest.get("target")
        direction = latest.get("direction", "higher")
        latest_value = float(latest["value"])

        target_class = ""
        if target is not None:
            if direction == "higher":
                target_class = "good" if latest_value >= float(target) else "bad"
            else:
                target_class = "good" if latest_value <= float(target) else "bad"

        # Sparkline (last 60 values)
        spark_values = values[-60:]
        if len(spark_values) > 1:
            spark_min, spark_max = min(spark_values), max(spark_values)
            spark_range = spark_max - spark_min or 1
            points = []
            for i, v in enumerate(spark_values):
                x = (i / max(len(spark_values) - 1, 1)) * 280
                y = 50 - ((v - spark_min) / spark_range) * 45
                points.append(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}")
            spark_path = " ".join(points)
        else:
            spark_path = ""

        cards.append(f"""
<div class="card">
  <div class="card-header"><h3>{name}</h3><span class="unit">{unit}</span></div>
  <div class="value {target_class}">{fmt_num(latest_value)}</div>
  <svg width="280" height="50" class="spark"><path d="{spark_path}" fill="none" stroke="#58a6ff" stroke-width="1.5"/></svg>
  <table class="stats">
    <tr><td>min</td><td>{fmt_num(stats_data['min'])}</td><td>p50</td><td>{fmt_num(stats_data['p50'])}</td></tr>
    <tr><td>max</td><td>{fmt_num(stats_data['max'])}</td><td>p95</td><td>{fmt_num(stats_data['p95'])}</td></tr>
    <tr><td>avg</td><td>{fmt_num(stats_data['mean'])}</td><td>p99</td><td>{fmt_num(stats_data['p99'])}</td></tr>
    <tr><td>n</td><td>{stats_data['n']}</td><td>target</td><td>{fmt_num(target)}</td></tr>
  </table>
</div>""")

    return HTMLResponse(f"""<!doctype html><html><head><title>{PROJECT} KPIs</title>
<meta http-equiv="refresh" content="60">
<style>
  body{{font-family:system-ui;max-width:1400px;margin:0 auto;padding:1em;background:#0d1117;color:#c9d1d9}}
  h1{{border-bottom:1px solid #30363d;padding-bottom:0.5em}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1em}}
  .card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1em}}
  .card-header{{display:flex;justify-content:space-between;align-items:baseline}}
  .card h3{{margin:0;font-size:1em;color:#79c0ff}}
  .unit{{color:#8b949e;font-size:0.85em}}
  .value{{font-size:2em;font-weight:bold;margin:0.5em 0}}
  .value.good{{color:#3fb950}}
  .value.bad{{color:#f85149}}
  .spark{{display:block;margin:0.5em 0;background:#0d1117;border-radius:4px}}
  .stats{{width:100%;font-size:0.85em;color:#8b949e}}
  .stats td{{padding:0.15em 0.5em}}
  .stats td:nth-child(2),.stats td:nth-child(4){{color:#c9d1d9;text-align:right}}
</style></head>
<body>
  <h1>{PROJECT} KPI Dashboard</h1>
  <p style="color:#8b949e">Auto-refresh: 60s · Data: <code>{KPI_DATA_FILE}</code> · <a href="/api/kpis" style="color:#58a6ff">JSON</a></p>
  <div class="grid">{''.join(cards)}</div>
</body></html>""")


if __name__ == "__main__":
    print(f"KPI dashboard starting on http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    print(f"Reading data from: {KPI_DATA_FILE}")
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT, log_level="info")
