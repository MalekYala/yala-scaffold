"""Polite fetching for <name>.

Separated from `extract.py` on purpose: extraction is pure, so it can be
tested against committed fixtures. This module is the impure half — network,
clock, retries — and is the part you should exercise sparingly and never in CI.

Politeness is not decoration. An unidentified scraper issuing requests as fast
as it can gets blocked, and deserves to be. Three things make the difference:
a real User-Agent that says who you are, a delay between requests, and honouring
what the site asks of you in robots.txt.
"""

from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

import config

settings = config.load()

# Identify yourself. A contactable UA is the difference between someone
# emailing you about load and someone silently null-routing your IP.
USER_AGENT = settings.user_agent
REQUEST_DELAY_S = float(settings.request_delay_s)
REQUEST_TIMEOUT_S = float(settings.request_timeout_s)
MAX_RETRIES = int(settings.max_retries)


@dataclass
class Response:
    url: str
    status: int
    text: str
    elapsed_ms: float


class Fetcher:
    """A rate-limited, robots-aware HTTP client."""

    def __init__(self, base_url: str = "", respect_robots: bool = True) -> None:
        self.base_url = base_url
        self.respect_robots = respect_robots
        self._last_request = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_S,
            follow_redirects=True,
        )

    def _wait(self) -> None:
        """Space requests out. The single most effective politeness measure."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < REQUEST_DELAY_S:
            time.sleep(REQUEST_DELAY_S - elapsed)
        self._last_request = time.monotonic()

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(urljoin(root, "/robots.txt"))
            try:
                parser.read()
            except Exception:
                # An unreachable robots.txt is not permission to ignore it, but
                # it is also not a reason to stop. Assume allowed and move on.
                return True
            self._robots[root] = parser
        return self._robots[root].can_fetch(USER_AGENT, url)

    def get(self, url: str) -> Response:
        """Fetch one URL, with backoff on transient failures."""
        full = urljoin(self.base_url, url) if self.base_url else url
        if not self.allowed(full):
            raise PermissionError(f"robots.txt disallows fetching {full}")

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._wait()
            started = time.perf_counter()
            try:
                response = self._client.get(full)
            except httpx.HTTPError as exc:
                last_error = exc
                # Exponential backoff: retrying immediately against a
                # struggling server makes its problem worse and yours longer.
                time.sleep(2 ** (attempt - 1))
                continue

            elapsed_ms = (time.perf_counter() - started) * 1000.0

            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(delay)
                last_error = httpx.HTTPStatusError(f"HTTP {response.status_code}", request=response.request, response=response)
                continue

            return Response(url=full, status=response.status_code, text=response.text, elapsed_ms=elapsed_ms)

        raise RuntimeError(f"giving up on {full} after {MAX_RETRIES} attempts: {last_error}")

    def close(self) -> None:
        self._client.close()
