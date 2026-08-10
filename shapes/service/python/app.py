"""Minimal FastAPI service stub for <name>.

Shape: service (long-running HTTP API).

The `/health` endpoint and structured perf logging conventions are required by
AGENTS.md — do not remove them. Replace the rest with your real implementation.

OPERATOR-MAINTAINED BLOCKS
--------------------------
Any code between `# operator:begin <tag>` and `# operator:end <tag>` is
considered a manual override that the regeneration pipeline's AI-driven regeneration MUST
preserve byte-for-byte. Use this for wiring that isn't captured in the
plan (e.g. custom auto-joins, side-channel listeners, startup hooks).

Example:
    # operator:begin irc-auto-join
    auto_join = os.environ.get("IRC_AUTO_JOIN", "").strip()
    if auto_join:
        for ch in [c.strip() for c in auto_join.split(",") if c.strip()]:
            await irc.join(ch)
    # operator:end irc-auto-join
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI

import config

# Every environment variable comes from here, validated, or the process does
# not start. Never read os.environ directly — see config.py for why.
settings = config.load()

PORT: int = settings.port
HOST: str = settings.host
LOG_LEVEL: str = settings.log_level

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>")

app = FastAPI(title="<name>", version=settings.app_version)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness/readiness probe. Returns 200 if the service and its critical
    dependencies are up. See AGENTS.md §14.

    The version is part of the response on purpose: during an incident the
    question is almost never "is something running" but "*which build* is
    running", and an endpoint that cannot answer that sends you to the
    deployment logs to guess.
    """
    _t = time.monotonic()
    # TODO: add real dependency checks (DB, Redis, downstream APIs)
    elapsed = int((time.monotonic() - _t) * 1000)
    log.info(f"[<name>-perf] phase=health duration_ms={elapsed} status=ok")
    return {
        "status": "ok",
        "service": "<name>",
        "version": settings.app_version,
        "env": settings.env,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
