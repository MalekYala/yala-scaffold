"""Shape-specific configuration for <name> (shape: bridge).

Everything a bridge needs to know about the thing it does not control.
"""

from __future__ import annotations

from config import Field, as_int, as_url

FIELDS: list[Field] = [
    Field(
        "UPSTREAM_URL",
        "Base URL of the service this bridges. Required — a bridge with no upstream has nothing to do.",
        cast=as_url,
        default="http://127.0.0.1:9000",
        section="Upstream",
    ),
    Field(
        "UPSTREAM_HEALTH_PATH",
        "Path on the upstream that /ready probes.",
        default="/health",
    ),
    Field(
        "UPSTREAM_TOKEN",
        "Credential sent upstream. Never echoed back to callers.",
        commented=True,
        secret=True,
    ),
    Field(
        "UPSTREAM_TIMEOUT_S",
        "Per-request timeout. Shorter than your caller's timeout, or you become the thing that times out.",
        default="30.0",
    ),
    Field(
        "BREAKER_THRESHOLD",
        "Consecutive upstream failures before the circuit breaker opens. Without a breaker, one upstream outage becomes two: theirs, and the retry storm you add to it.",
        cast=as_int,
        default=5,
        section="Circuit breaker",
    ),
    Field(
        "BREAKER_COOLDOWN_S",
        "Seconds the breaker stays open before letting one request through.",
        default="30.0",
    ),
]
