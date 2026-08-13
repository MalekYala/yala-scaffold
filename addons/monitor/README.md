# Monitor add-on — `<name>`

A scheduled external prober. `kpi.json` declares what matters and `qa_check`
verifies it on demand; this runs on a timer, when nobody is watching.

## What you need

Somewhere to run it on a schedule (cron, a systemd timer, a CI schedule) and
somewhere to keep the output. That is all — the probe has no dependencies
beyond the Python standard library and writes an append-only JSONL file.

## Use

```bash
python3 monitor/probe.py                    # probe now, print results
python3 monitor/probe.py --quiet            # print only on failure
python3 monitor/probe.py --out data/probes.jsonl
```

It probes `/health`, plus every KPI in `kpi.json` whose `source.url` is an HTTP
endpoint. A relative `source.url` (starting `/`) is resolved against
`--base-url`.

## Scheduling

Cron, every five minutes, mailing you only when something fails:

```cron
*/5 * * * * cd /path/to/<name> && python3 monitor/probe.py --quiet
```

A systemd timer is better if you want the history in `journalctl`:

```ini
# <name>-probe.service
[Service]
Type=oneshot
WorkingDirectory=/path/to/<name>
ExecStart=/usr/bin/python3 monitor/probe.py --quiet
```

```ini
# <name>-probe.timer
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
```

## Output

One JSON object per line in `data/probes.jsonl`:

```json
{"timestamp":"2026-01-01T00:00:00+00:00","project":"<name>","failed":0,
 "probes":[{"name":"health","url":"...","ok":true,"status":200,"latency_ms":3.2}]}
```

JSONL because it is append-only, survives a crash mid-write, and every tool
already reads it. Point `--out` at a path your existing collector ingests, or
post-process it with `jq`.

The file grows without bound — rotate it (`logrotate`, or a `find -mtime`
cleanup) if this runs indefinitely.

## Exit codes

`0` when every probe passed, `1` when any failed, `2` on a configuration error.
The non-zero exit is what makes `--quiet` useful under cron: silence means
healthy, mail means broken.

## What this is not

Not a replacement for real monitoring. There is no alerting, no deduplication,
no escalation, no history beyond the file. It answers "was this up five minutes
ago" from one vantage point.

If you need alerting, multi-region checks, or on-call routing, use a hosted
synthetic-monitoring service and keep this as the local smoke check.
