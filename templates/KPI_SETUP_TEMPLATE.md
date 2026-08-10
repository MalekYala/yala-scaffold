# KPI Monitoring — Setup Guide

This project ships with `kpi.json`, a declarative file describing the metrics it considers important. It does **not** include a running collector or dashboard — those are deployment-specific. This document shows you how to wire it into your own monitoring stack.

You have three paths, in order of complexity:

1. **[Path A — Reference collector + simple dashboard](#path-a)** (5 minutes, no extra services)
2. **[Path B — Prometheus + Grafana](#path-b)** (battle-tested, scales to many projects)
3. **[Path C — SaaS dashboard](#path-c)** (zero ops, costs money)

---

## Quick start

```bash
# Path A — run the bundled portable collector
python3 scripts/kpi_collector.py --once
# Look at the output:
cat data/kpis.jsonl
```

If you just want to see KPI values right now without setting anything up, that's it.

---

## How `kpi.json` works

`kpi.json` is a declarative file. Each KPI has a `name`, a `source` (how to fetch the value), a `kpi_type`, a `direction` (higher or lower is better), and an optional `target`.

```json
{
  "project": "<name>",
  "kpis": [
    {
      "name": "health_up",
      "kpi_type": "boolean",
      "unit": "bool",
      "direction": "higher",
      "target": 1,
      "interval_s": 60,
      "source": {
        "type": "http_status",
        "url": "http://127.0.0.1:8500/health",
        "expect_status": 200
      },
      "description": "Service is up and /health returns 2xx"
    }
  ]
}
```

A KPI collector reads this file, evaluates each `source` on its `interval_s` schedule, and writes the value somewhere persistent. A dashboard reads those persisted values and visualizes them.

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | Unique within the project. Use `snake_case`. |
| `kpi_type` | string | yes | One of: `boolean`, `gauge`, `counter`, `float`. Used for visualization hints only. |
| `unit` | string | no | e.g. `ms`, `bytes`, `rps`, `%`, `ratio`. Display only. |
| `direction` | string | yes | `higher` or `lower` — which direction is "better". |
| `target` | number | no | If set, dashboards color the value green (meeting target) or red (missing). |
| `interval_s` | int | yes | How often to evaluate this KPI, in seconds. |
| `source` | object | yes | How to collect the value. See [source types](#source-types) below. |
| `description` | string | no | Human-readable explanation. |

### Source types

#### `http_status`

Returns `1` if the URL returns the expected status code, else `0`.

```json
{
  "type": "http_status",
  "url": "http://127.0.0.1:8500/health",
  "expect_status": 200
}
```

#### `http_latency`

Returns the request duration in milliseconds. Useful for tracking endpoint latency over time.

```json
{
  "type": "http_latency",
  "url": "http://127.0.0.1:8500/health"
}
```

#### `http_json`

Fetches a URL, parses it as JSON, extracts a dotted-path field, and returns it as a float.

```json
{
  "type": "http_json",
  "url": "http://127.0.0.1:8500/stats",
  "field": "result.score"
}
```

#### `shell`

Runs a shell command in the project directory. The collector parses the **last numeric line** of stdout as the value.

```json
{
  "type": "shell",
  "cmd": "./metric.sh",
  "timeout_s": 60
}
```

The default `qa_score` KPI uses this with `./metric.sh`, which runs `qa_check.py` and prints the pass ratio.

#### `metric_log_grep`

Greps a log file for a regex pattern, optionally extracts a numeric capture group, and aggregates the matches over a time window. **This is the killer feature** — it lets you turn your existing log lines into metrics without adding a Prometheus exporter.

```json
{
  "type": "metric_log_grep",
  "log_file": "logs/app.log",
  "pattern": "duration_ms=(\\d+)",
  "window_s": 300,
  "aggregate": "p99"
}
```

`aggregate` can be: `count`, `sum`, `mean`, `max`, `p50`, `p90`, `p95`, `p99`.

If you follow the `[<project>-perf] phase=X duration_ms=N` log convention from `AGENTS.md` §8, you get latency percentiles for free.

#### `sql`

Runs a SQL query against a Postgres database and returns the first column of the first row as a float.

```json
{
  "type": "sql",
  "db": "myapp",
  "query": "SELECT count(*) FROM users WHERE created_at > now() - interval '1 day'"
}
```

#### `static`

Returns a fixed value. For testing.

```json
{
  "type": "static",
  "value": 42
}
```

---

## Path A — Reference collector + simple dashboard

This is the fastest way to start. The bundled `scripts/kpi_collector.py` is a portable, dependency-light Python script that reads `kpi.json`, collects values, and writes them to a JSONL file (`data/kpis.jsonl`). A tiny FastAPI dashboard at `scripts/kpi_dashboard.py` reads that file and serves an HTML page.

### Setup

```bash
# 1. Install collector dependencies (just httpx and python-dotenv)
pip install httpx python-dotenv fastapi uvicorn

# 2. Run the collector once to verify it works
python3 scripts/kpi_collector.py --once
cat data/kpis.jsonl

# 3. Run the collector as a daemon (every 60s)
python3 scripts/kpi_collector.py &

# 4. Start the dashboard
python3 scripts/kpi_dashboard.py
# Open http://127.0.0.1:9090
```

### Running both as systemd services (Linux)

Create `/etc/systemd/system/<name>-kpi-collector.service`:

```ini
[Unit]
Description=<name> KPI collector
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/<name>
ExecStart=/usr/bin/python3 scripts/kpi_collector.py
Restart=always
RestartSec=10
User=youruser

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now <name>-kpi-collector.service
```

### Running as a Docker sidecar

Add this to your `docker-compose.yml`:

```yaml
  kpi-collector:
    build: .
    command: python3 scripts/kpi_collector.py
    volumes:
      - ./kpi.json:/app/kpi.json:ro
      - ./data:/app/data
    depends_on:
      - <name>
    restart: unless-stopped
    mem_limit: 128m
```

### Where the data lives

The reference collector writes to `data/kpis.jsonl` (one line per measurement):

```json
{"ts": 1775500000, "project": "<name>", "name": "health_up", "value": 1.0, "metadata": {"status": 200}}
{"ts": 1775500060, "project": "<name>", "name": "health_latency_ms", "value": 12.4, "metadata": {"status": 200}}
```

JSONL is grep-friendly, can be tailed, and any analytics tool understands it.

---

## Path B — Prometheus + Grafana

Standard observability stack. More work upfront, more capabilities afterward (alerting, multi-project dashboards, long-term storage).

### Approach 1: Textfile exporter (simplest)

Have the bundled `kpi_collector.py` write Prometheus textfile format instead of JSONL. The Prometheus node_exporter (with `--collector.textfile.directory=/var/lib/node_exporter/textfile_collector`) picks them up automatically.

Add a `--format prometheus` flag to your collector invocation:

```bash
python3 scripts/kpi_collector.py --format prometheus --output /var/lib/node_exporter/textfile_collector/<name>.prom
```

The collector writes a `.prom` file like:

```
# HELP <name>_health_up Service is up and /health returns 2xx
# TYPE <name>_health_up gauge
<name>_health_up 1
# HELP <name>_health_latency_ms How long /health takes to respond
# TYPE <name>_health_latency_ms gauge
<name>_health_latency_ms 12.4
```

Prometheus scrapes this every 15s. Grafana queries Prometheus and renders dashboards.

### Approach 2: Direct push to Prometheus pushgateway

If you can't run a textfile exporter (no host access, no node_exporter), push to a Pushgateway:

```bash
python3 scripts/kpi_collector.py --format prometheus-push --pushgateway http://pushgateway:9091
```

Note: pushgateway is intended for batch jobs. For long-running services, prefer textfile or pull-based scraping.

### Grafana dashboard JSON

A starter Grafana dashboard JSON for any project tracking the standard 3 KPIs:

```json
{
  "title": "<name> KPIs",
  "panels": [
    {
      "title": "Health Up",
      "type": "stat",
      "targets": [{"expr": "<name>_health_up"}]
    },
    {
      "title": "Health Latency (ms)",
      "type": "graph",
      "targets": [{"expr": "<name>_health_latency_ms"}]
    },
    {
      "title": "QA Score",
      "type": "gauge",
      "targets": [{"expr": "<name>_qa_score"}]
    }
  ]
}
```

Import via Grafana UI: Dashboards → New → Import → paste JSON.

---

## Path C — SaaS dashboard

If you don't want to run any collector or dashboard infrastructure, the bundled `kpi_collector.py` can push to several SaaS services with the right `--format` flag.

| Service | Flag | Auth |
|---|---|---|
| Datadog | `--format datadog --api-key $DD_API_KEY` | API key |
| Grafana Cloud | `--format prometheus-push --pushgateway https://...` | Bearer token |
| New Relic | `--format newrelic --api-key $NR_API_KEY` | API key |
| Honeycomb | `--format honeycomb --api-key $HONEYCOMB_API_KEY --dataset <name>` | API key |

Add the API key to `.env`:

```bash
DD_API_KEY=your_datadog_key
```

Then run the collector as in Path A. Each tick pushes the current values to the SaaS endpoint.

---

## Defining KPIs for YOUR project

The 3 default KPIs (`health_up`, `health_latency_ms`, `qa_score`) are a baseline. The real value is in defining KPIs that capture YOUR project's success criteria.

### Examples by project type

**API service:**
```json
{
  "name": "p99_request_latency_ms",
  "source": {"type": "metric_log_grep", "log_file": "logs/app.log", "pattern": "phase=request duration_ms=(\\d+)", "window_s": 300, "aggregate": "p99"},
  "direction": "lower",
  "target": 200
},
{
  "name": "error_rate_5xx",
  "source": {"type": "metric_log_grep", "log_file": "logs/app.log", "pattern": "status=5\\d\\d", "window_s": 300, "aggregate": "count"},
  "direction": "lower",
  "target": 0
}
```

**Worker / batch:**
```json
{
  "name": "jobs_per_minute",
  "source": {"type": "metric_log_grep", "log_file": "logs/worker.log", "pattern": "phase=job_complete", "window_s": 60, "aggregate": "count"},
  "direction": "higher"
},
{
  "name": "queue_depth",
  "source": {"type": "http_json", "url": "http://127.0.0.1:8500/queue/stats", "field": "pending"},
  "direction": "lower",
  "target": 100
}
```

**ML / inference:**
```json
{
  "name": "tokens_per_second",
  "source": {"type": "metric_log_grep", "log_file": "logs/inference.log", "pattern": "tokens_per_sec=(\\d+\\.\\d+)", "window_s": 300, "aggregate": "mean"},
  "direction": "higher"
},
{
  "name": "vram_used_gb",
  "source": {"type": "shell", "cmd": "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | awk '{print $1/1024}'"},
  "direction": "lower",
  "target": 20
}
```

**Database service:**
```json
{
  "name": "active_connections",
  "source": {"type": "sql", "db": "myapp", "query": "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"},
  "direction": "lower",
  "target": 50
}
```

### Setting good targets

- A target you constantly miss → either the target is wrong (raise the bar) or the project has a problem (fix it)
- A target you always hit easily → tighten the target
- A KPI without a target is just a chart — set targets to make them actionable

---

## Querying the data

### JSONL (Path A)

```bash
# Latest health_up value
tail -100 data/kpis.jsonl | grep '"name": "health_up"' | tail -1 | jq '.value'

# Average qa_score over last 100 measurements
tail -1000 data/kpis.jsonl | grep '"name": "qa_score"' | tail -100 | jq '.value' | awk '{s+=$1} END {print s/NR}'

# Time series chart (use jq + plot)
tail -10000 data/kpis.jsonl | grep '"name": "health_latency_ms"' | jq -r '[.ts, .value] | @tsv' > latency.tsv
gnuplot -e "set terminal dumb; plot 'latency.tsv' using 1:2 with lines"
```

### Prometheus (Path B)

PromQL queries:

```promql
# Current value
<name>_health_up

# Average over last 5 minutes
avg_over_time(<name>_health_latency_ms[5m])

# Rate of changes
rate(<name>_request_count[1m])

# Alert if health_up drops to 0 for more than 1 minute
ALERT <name>_down
  IF <name>_health_up == 0
  FOR 1m
  ANNOTATIONS { summary = "<name> is down" }
```

---

## Alerting

### Path A: simple

Add a check to your existing healthcheck/uptime monitoring (Uptime Kuma, healthchecks.io, custom cron):

```bash
# Cron: every 5 minutes, alert if health_up has been 0 for the last 5 minutes
*/5 * * * * tail -10 /path/to/data/kpis.jsonl | grep '"name": "health_up"' | tail -5 | jq '.value' | grep -v '^1' && curl -X POST 'https://hc-ping.com/<uuid>/fail'
```

### Path B: Prometheus Alertmanager

Define rules in `prometheus.rules.yml`:

```yaml
groups:
  - name: <name>
    rules:
      - alert: <name>_down
        expr: <name>_health_up == 0
        for: 1m
        annotations:
          summary: "<name> is down"
      - alert: <name>_slow
        expr: <name>_health_latency_ms > 500
        for: 5m
        annotations:
          summary: "<name> /health is slow"
      - alert: <name>_qa_failing
        expr: <name>_qa_score < 0.8
        for: 5m
        annotations:
          summary: "<name> qa_check is failing tests"
```

Wire Alertmanager to PagerDuty / Slack / email / your incident tool of choice.

---

## Troubleshooting

### Collector says "no numeric output" for shell sources

The shell command must print a single numeric value as the **last line** of stdout. If your script prints log lines first, redirect them to stderr:

```bash
echo "doing stuff..." >&2
echo "0.95"  # this is what the collector reads
```

### `metric_log_grep` always returns 0

- Check that the log file exists and is being written to
- Make sure the regex compiles (`python3 -c "import re; re.compile(r'your-pattern')"`)
- The regex must match SOMETHING in the log (run `grep -E 'your-pattern' logfile` to verify)
- For percentile aggregates (`p50`, `p99`), the regex must have a numeric capture group: `duration_ms=(\d+)` not `duration_ms=\d+`

### `http_status` always returns 0

- Verify the URL is reachable from where the collector runs (especially in Docker — `127.0.0.1` from inside a container ≠ host)
- Use `host.docker.internal` (Docker Desktop) or the container name on a shared network
- Check the actual status code: `curl -w "%{http_code}\n" -o /dev/null -s <url>`

### My KPIs are noisy

- Increase `interval_s` so you sample less frequently
- Use `metric_log_grep` with a wider `window_s` to smooth over short bursts
- For percentiles (`p99`), increase `window_s` to at least 5 minutes (300s) — anything less is statistically unreliable

---

## See also

- [`AGENTS.md`](AGENTS.md) §17 — KPI conventions for this project
- [`scripts/kpi_collector.py`](scripts/kpi_collector.py) — the bundled portable collector
- [`scripts/kpi_dashboard.py`](scripts/kpi_dashboard.py) — the bundled portable dashboard
- [Prometheus textfile collector docs](https://github.com/prometheus/node_exporter#textfile-collector)
- [Grafana dashboards](https://grafana.com/grafana/dashboards/)
