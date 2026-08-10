"""Background worker stub for <name>.

Shape: worker (long-running background process, no HTTP surface).

The main loop does three things on every tick:
    1. Touches data/heartbeat so the compose healthcheck stays green.
    2. Pulls a batch of work (replace `pull_batch` with your real source).
    3. Processes each item and emits structured perf logs per AGENTS.md §8.

Stop conditions: SIGTERM (handled gracefully) or the file `STOP_WORKER` in
the working directory (useful for autoresearch iterations).
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Any

from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "info").upper()
POLL_INTERVAL_S: int = int(os.environ.get("POLL_INTERVAL_S", "5"))
BATCH_SIZE: int = int(os.environ.get("BATCH_SIZE", "10"))
DATA_DIR: Path = Path(os.environ.get("DATA_DIR", "data"))
HEARTBEAT: Path = DATA_DIR / "heartbeat"
STOP_FILE: Path = Path("STOP_WORKER")

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>")

_shutdown: bool = False


def _sigterm_handler(signum: int, frame: FrameType | None) -> None:
    global _shutdown
    log.info("received SIGTERM — finishing current batch then exiting")
    _shutdown = True


signal.signal(signal.SIGTERM, _sigterm_handler)
signal.signal(signal.SIGINT, _sigterm_handler)


def pull_batch() -> list[dict[str, Any]]:
    """Pull up to BATCH_SIZE items of work. Replace with a real source:
    Redis list pop, SQS receive, database SELECT FOR UPDATE SKIP LOCKED, etc.

    Returns an empty list when there's no work. Called on every tick.
    """
    # TODO: replace with real source
    return []


def process_item(item: dict[str, Any]) -> bool:
    """Process a single item. Return True on success, False on failure.

    Must be idempotent — the same item may be delivered more than once
    (see AGENTS.md §12).
    """
    # TODO: replace with real work
    return True


def touch_heartbeat() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.touch()


def main() -> None:
    log.info(f"<name> worker starting (batch_size={BATCH_SIZE} poll={POLL_INTERVAL_S}s)")
    touch_heartbeat()

    while not _shutdown:
        if STOP_FILE.exists():
            log.info("STOP_WORKER file found — exiting")
            break

        _t_loop = time.monotonic()
        touch_heartbeat()

        _t_pull = time.monotonic()
        batch = pull_batch()
        pull_ms = int((time.monotonic() - _t_pull) * 1000)
        log.info(f"[<name>-perf] phase=pull duration_ms={pull_ms} count={len(batch)}")

        ok_count = 0
        for item in batch:
            _t_proc = time.monotonic()
            try:
                if process_item(item):
                    ok_count += 1
                proc_ms = int((time.monotonic() - _t_proc) * 1000)
                log.info(f"[<name>-perf] phase=process duration_ms={proc_ms} status=ok")
            except Exception as exc:
                proc_ms = int((time.monotonic() - _t_proc) * 1000)
                log.warning(f"[<name>-perf] phase=process duration_ms={proc_ms} status=fail error={exc}")

        loop_ms = int((time.monotonic() - _t_loop) * 1000)
        log.info(f"[<name>-perf] phase=loop duration_ms={loop_ms} batch={len(batch)} ok={ok_count}")

        if not batch:
            time.sleep(POLL_INTERVAL_S)

    log.info("<name> worker exited cleanly")


if __name__ == "__main__":
    main()
    sys.exit(0)
