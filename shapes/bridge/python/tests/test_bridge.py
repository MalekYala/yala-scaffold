"""Tests for <name>'s bridge behaviour.

These cover what a bridge does when the thing it wraps misbehaves — which is
where a bridge's real contract lives. A bridge tested only against a healthy
upstream is untested for every case that matters.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app as bridge  # noqa: E402


@pytest.fixture(autouse=True)
def dead_upstream(monkeypatch):
    """Point the bridge at a port nothing is listening on.

    Without this the suite depends on what happens to be running on the
    default port of whatever machine it runs on — which is how a test passes
    on a laptop and fails in CI, or worse, the reverse.
    """
    monkeypatch.setitem(bridge.settings.values, "UPSTREAM_URL", "http://127.0.0.1:1")
    bridge.breaker.failures = 0
    bridge.breaker.opened_at = 0.0


@pytest.fixture
def client() -> Iterator[TestClient]:
    # `with` runs the lifespan, which owns the upstream client. Constructing
    # TestClient without it leaves the client unbuilt.
    with TestClient(bridge.app) as test_client:
        yield test_client


class TestHealthVersusReady:
    def test_health_does_not_touch_the_upstream(self, client: TestClient) -> None:
        # If /health probed the upstream, an upstream outage would get a
        # perfectly healthy bridge restarted — losing in-flight requests and
        # helping nobody.
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_reports_the_build_version(self, client: TestClient) -> None:
        assert response_version(client) != ""

    def test_ready_reports_the_upstream(self, client: TestClient) -> None:
        # No upstream is running in tests, so this must be honest about that
        # rather than claiming readiness.
        response = client.get("/ready")
        body = response.json()
        assert "upstream" in body
        assert response.status_code == 503
        assert body["status"] == "degraded"


def response_version(client: TestClient) -> str:
    return str(client.get("/health").json().get("version", ""))


class TestDegradation:
    def test_unreachable_upstream_is_not_a_500(self, client: TestClient) -> None:
        # A bare 500 claims the fault is here and invites the caller to retry
        # into an upstream that is already struggling.
        response = client.get("/proxy/anything")
        assert response.status_code in (502, 503, 504)
        assert response.status_code != 500


class TestHeaderHygiene:
    def test_caller_credentials_are_never_forwarded(self) -> None:
        for header in ("authorization", "cookie", "x-api-key", "proxy-authorization"):
            assert header in bridge.STRIP_REQUEST_HEADERS, header

    def test_upstream_auth_headers_are_never_returned(self) -> None:
        for header in ("set-cookie", "www-authenticate", "proxy-authenticate"):
            assert header in bridge.STRIP_RESPONSE_HEADERS, header

    def test_hop_by_hop_headers_are_stripped(self) -> None:
        # Forwarding these corrupts the response framing.
        for header in ("content-length", "transfer-encoding", "connection"):
            assert header in bridge.STRIP_RESPONSE_HEADERS, header


class TestCircuitBreaker:
    def test_stays_closed_below_the_threshold(self) -> None:
        breaker = bridge.CircuitBreaker(threshold=3, cooldown_s=60)
        breaker.record_failure()
        breaker.record_failure()
        assert not breaker.is_open

    def test_opens_at_the_threshold(self) -> None:
        breaker = bridge.CircuitBreaker(threshold=3, cooldown_s=60)
        for _ in range(3):
            breaker.record_failure()
        assert breaker.is_open

    def test_a_success_resets_it(self) -> None:
        breaker = bridge.CircuitBreaker(threshold=2, cooldown_s=60)
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        assert not breaker.is_open

    def test_half_opens_after_the_cooldown(self) -> None:
        # It must let one request through eventually, or a recovered upstream
        # never gets noticed.
        breaker = bridge.CircuitBreaker(threshold=1, cooldown_s=0.05)
        breaker.record_failure()
        assert breaker.is_open
        time.sleep(0.06)
        assert not breaker.is_open
