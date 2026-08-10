"""Serve the committed fixture site for <name>.

Binds to an **ephemeral port** (port 0) rather than a fixed one, and reports
back which port it got. On any machine running more than a handful of services
a hardcoded port is a coin flip, and losing it produces a browser test that
fails against somebody else's service — which looks like a broken selector and
wastes an afternoon.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent / "site"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return  # request logs drown the actual test output


class FixtureSite:
    """A local static server, started and stopped around a test run."""

    def __init__(self, directory: Path = SITE_DIR) -> None:
        handler = functools.partial(QuietHandler, directory=str(directory))
        self._server = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port: int = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> FixtureSite:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
