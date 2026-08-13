"""Upstream bridge for <name>.

Shape: bridge (wrap an upstream service behind your own interface).

A bridge is a `service` whose behaviour is dominated by something it does not
control. That changes what "working" means, in three ways this file is built
around:

**Its health is two questions, not one.** "Am I running?" and "can I reach the
upstream?" are different, and collapsing them is how a bridge either gets
restarted for an outage that is not its fault, or reports healthy while
serving nothing. `/health` answers the first, `/ready` answers both.

**Upstream failure must degrade, not explode.** A 500 tells the caller *you*
are broken and invites a retry storm against an upstream that is already
struggling. 502/503/504 say where the problem is, and a circuit breaker stops
you from being the load that keeps it down.

**Credentials must not leak in either direction.** The token you use upstream
must never appear in a response, and the caller's headers must not be blindly
forwarded. Both are easy to do by accident when proxying.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

import config

settings = config.load()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>")

_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Own the upstream client's lifetime.

    An httpx.AsyncClient is bound to the event loop that created it. Building
    it lazily on first use means it can outlive that loop — which surfaces as
    a baffling "Event loop is closed" the moment anything creates a second
    one, tests being the usual first victim. Creating it here ties it to the
    application's own loop.
    """
    global _client
    headers = {"User-Agent": f"<name>/{settings.app_version}"}
    if settings.upstream_token:
        # Our credential, added here and never echoed back to the caller.
        headers["Authorization"] = f"Bearer {settings.upstream_token}"
    _client = httpx.AsyncClient(
        base_url=settings.upstream_url,
        timeout=float(settings.upstream_timeout_s),
        headers=headers,
    )
    try:
        yield
    finally:
        await _client.aclose()
        _client = None


app = FastAPI(title="<name>", version=settings.app_version, lifespan=lifespan)

# Headers that must never be forwarded upstream: they either leak the caller's
# credentials to a third party or confuse the upstream about who is asking.
STRIP_REQUEST_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "host",
    "content-length",
}

# Headers that must never come back to the caller.
STRIP_RESPONSE_HEADERS = {
    "set-cookie",
    "www-authenticate",
    "proxy-authenticate",
    "content-length",
    "transfer-encoding",
    "connection",
}


class CircuitBreaker:
    """Stop hammering an upstream that is already failing.

    Without this, a bridge turns one upstream outage into two: theirs, and the
    retry storm you add to it. After `threshold` consecutive failures the
    breaker opens and requests fail immediately for `cooldown_s`, giving the
    upstream room to recover.
    """

    def __init__(self, threshold: int, cooldown_s: float) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = 0
        self.opened_at = 0.0

    @property
    def is_open(self) -> bool:
        if self.failures < self.threshold:
            return False
        if time.monotonic() - self.opened_at >= self.cooldown_s:
            # Half-open: let one request through to test the water.
            self.failures = self.threshold - 1
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


breaker = CircuitBreaker(settings.breaker_threshold, float(settings.breaker_cooldown_s))


def client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("upstream client is not initialised — did the app lifespan run?")
    return _client


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness only: is *this process* alive?

    Deliberately does not touch the upstream. If it did, an upstream outage
    would make an orchestrator restart a perfectly healthy bridge — which
    helps nobody and loses your in-flight requests.
    """
    return {
        "status": "ok",
        "service": "<name>",
        "version": settings.app_version,
        "env": settings.env,
    }


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness: can this bridge actually do its job right now?

    Reports the upstream's state without pretending to be it. A bridge that
    cannot reach its upstream is not ready, and saying so plainly is what lets
    a load balancer route around it instead of serving errors.
    """
    started = time.perf_counter()
    detail: dict[str, Any] = {
        "service": "<name>",
        "upstream": settings.upstream_url,
        "breaker_open": breaker.is_open,
    }

    if breaker.is_open:
        detail["status"] = "degraded"
        detail["reason"] = "circuit breaker open after repeated upstream failures"
        return JSONResponse(detail, status_code=503)

    try:
        response = await client().get(settings.upstream_health_path)
        elapsed = (time.perf_counter() - started) * 1000
        ok = response.status_code < 500
        detail["status"] = "ok" if ok else "degraded"
        detail["upstream_status"] = response.status_code
        detail["latency_ms"] = round(elapsed, 1)
        log.info(f"[<name>-perf] phase=ready duration_ms={elapsed:.0f} upstream_status={response.status_code}")
        return JSONResponse(detail, status_code=200 if ok else 503)
    except httpx.HTTPError as exc:
        detail["status"] = "degraded"
        # The exception type, not the message: messages can carry the URL
        # including any credential embedded in it.
        detail["reason"] = f"upstream unreachable ({type(exc).__name__})"
        return JSONResponse(detail, status_code=503)


@app.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request) -> JSONResponse:
    """Forward a request upstream and map failures honestly.

    The status code says *where* the problem is:
      502  upstream returned something unusable
      503  circuit breaker open, or upstream unreachable
      504  upstream took too long

    A blanket 500 would claim the fault is here and invite the caller to retry
    into an upstream that is already struggling.
    """
    if breaker.is_open:
        raise HTTPException(
            status_code=503,
            detail="upstream is failing; circuit breaker open. Retry after the cooldown.",
        )

    forwarded = {key: value for key, value in request.headers.items() if key.lower() not in STRIP_REQUEST_HEADERS}
    body = await request.body()

    started = time.perf_counter()
    try:
        upstream = await client().request(
            request.method,
            f"/{path}",
            content=body or None,
            params=dict(request.query_params),
            headers=forwarded,
        )
    except httpx.TimeoutException:
        breaker.record_failure()
        log.warning(f"upstream timeout for /{path}")
        raise HTTPException(status_code=504, detail="upstream timed out") from None
    except httpx.HTTPError as exc:
        breaker.record_failure()
        log.warning(f"upstream unreachable for /{path}: {type(exc).__name__}")
        raise HTTPException(status_code=503, detail="upstream unreachable") from None

    elapsed = (time.perf_counter() - started) * 1000
    if upstream.status_code >= 500:
        breaker.record_failure()
    else:
        breaker.record_success()

    log.info(f"[<name>-perf] phase=proxy duration_ms={elapsed:.0f} path=/{path} upstream_status={upstream.status_code}")

    safe_headers = {key: value for key, value in upstream.headers.items() if key.lower() not in STRIP_RESPONSE_HEADERS}

    try:
        payload = upstream.json()
    except ValueError:
        # Non-JSON from an upstream this bridge presents as JSON is a 502:
        # the upstream is misbehaving, not the caller.
        raise HTTPException(status_code=502, detail="upstream returned a non-JSON response") from None

    return JSONResponse(payload, status_code=upstream.status_code, headers=safe_headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
