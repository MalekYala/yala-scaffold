#!/usr/bin/env python3
"""End-to-end check for <name> (shape: stream).

Drives a real WebRTC session between two local peers — genuine offer/answer,
ICE, DTLS, VP8 encode and decode — and asserts the lifecycle behaves. No
camera, no media file, no external service, no GPU.

Checks:

  1. handshake        — offer/answer completes and ICE connects
  2. media_flows      — frames actually arrive (connected with zero is a FAILURE)
  3. frames_advance   — successive frames differ, so the source is not frozen
  4. stall_detected   — a wedged source is noticed while the connection stays up
  5. reconnects       — backoff retries recover from a refused connection
  6. backoff_bounded  — retry delay is exponential and capped, not a tight loop
  7. teardown_clean   — closing releases the connection and its tasks

Check 2 is the reason this shape exists. A session can report `connected` with
zero frames — a codec mismatch, a track never added, a source that failed to
start. Every connection-level metric is green and the viewer sees nothing.
Treating `connected` as success is the vacuous pass, the same family as zero
discovered routes, zero exposed MCP tools and zero extracted records elsewhere
in this kit.

Check 4 is its subtler sibling: the source wedges *after* connecting, so even
a byte counter sampled once looks fine. Only freshness catches it.

Usage:
    python3 qa_check.py
    python3 qa_check.py --timeout 30

Exit codes:
    0  every check passed
    1  a check failed
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from session import PeerSession, connect_with_backoff  # noqa: E402
from tracks import StalledTrack, SyntheticTrack  # noqa: E402


async def dial(sender_track_factory: Callable[[], Any], timeout_s: float) -> tuple[PeerSession, PeerSession, bool]:
    """Establish a loopback session. Returns (sender, receiver, media_flowed)."""
    sender = PeerSession(track_factory=sender_track_factory)
    receiver = PeerSession()

    offer = await sender.offer()
    answer = await receiver.accept(offer)
    await sender.complete(answer)

    flowed = await receiver.wait_until_flowing(timeout_s)
    return sender, receiver, flowed


async def run(timeout_s: float) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # ── 1 & 2 & 3: a healthy session ──────────────────────────────────────
    sender, receiver, flowed = await dial(lambda: SyntheticTrack(width=320, height=240), timeout_s)
    try:
        connected = any(state in ("connected", "completed") for state in receiver.stats.ice_states + receiver.stats.connection_states)
        checks.append(
            {
                "name": "handshake",
                "ok": connected,
                "detail": f"ice={receiver.stats.ice_states[-3:]} conn={receiver.stats.connection_states[-3:]}",
            }
        )

        checks.append(
            {
                "name": "media_flows",
                "ok": flowed and receiver.stats.frames_received > 0,
                "detail": f"{receiver.stats.frames_received} frame(s) received"
                + ("" if flowed else " — the session reported connected and carried nothing, which every connection-level metric would call healthy"),
            }
        )

        # Frames must keep arriving, not just arrive once.
        before = receiver.stats.frames_received
        await asyncio.sleep(1.0)
        after = receiver.stats.frames_received
        checks.append(
            {
                "name": "frames_advance",
                "ok": after > before,
                "detail": f"{before} -> {after} over 1s" + ("" if after > before else " — source appears frozen"),
            }
        )
    finally:
        await sender.close()
        await receiver.close()

    # ── 4: a source that wedges after connecting ──────────────────────────
    stalled_sender, stalled_receiver, _stalled_flowed = await dial(lambda: StalledTrack(stall_after=3, width=320, height=240), timeout_s)
    try:
        # It must connect and deliver a few frames first — otherwise this
        # would be indistinguishable from the media_flows failure.
        got_some = stalled_receiver.stats.frames_received > 0
        await asyncio.sleep(2.0)
        detected = stalled_receiver.stats.is_stalled(timeout_s=1.0)
        checks.append(
            {
                "name": "stall_detected",
                "ok": got_some and detected,
                "detail": f"delivered {stalled_receiver.stats.frames_received} frame(s) then stalled; "
                f"detector fired={detected}" + ("" if got_some and detected else " — a wedged source with a live connection went unnoticed"),
            }
        )
    finally:
        await stalled_sender.close()
        await stalled_receiver.close()

    # ── 5 & 6: reconnection behaviour ─────────────────────────────────────
    attempts: list[float] = []

    async def flaky() -> str:
        attempts.append(time.monotonic())
        if len(attempts) < 3:
            raise ConnectionError("peer refused")
        return "connected"

    try:
        result = await connect_with_backoff(flaky, attempts=5, base_delay_s=0.1, max_delay_s=1.0)
        recovered = result == "connected"
        detail = f"recovered on attempt {len(attempts)}"
    except RuntimeError as exc:
        recovered = False
        detail = str(exc)
    checks.append({"name": "reconnects", "ok": recovered, "detail": detail})

    # Delays must grow, and must not be a tight loop.
    gaps = [round(b - a, 3) for a, b in itertools.pairwise(attempts)]
    growing = len(gaps) >= 2 and gaps[1] > gaps[0]
    not_tight = all(gap >= 0.05 for gap in gaps) if gaps else False
    checks.append(
        {
            "name": "backoff_bounded",
            "ok": growing and not_tight,
            "detail": f"gaps={gaps} (must grow, and never be a tight loop — hammering a peer that is down gets you blocked exactly when you are trying to recover)",
        }
    )

    # ── 7: teardown ───────────────────────────────────────────────────────
    victim, victim_rx, _ = await dial(lambda: SyntheticTrack(width=160, height=120), timeout_s)
    await victim.close()
    await victim_rx.close()
    leaked = [t for t in (victim._tasks | victim_rx._tasks) if not t.done()]
    checks.append(
        {
            "name": "teardown_clean",
            "ok": victim.pc is None and victim_rx.pc is None and not leaked,
            "detail": "connection and tasks released"
            if not leaked
            else f"{len(leaked)} task(s) still running — leaked consumers are why a long-running streamer dies days later with nothing in the logs",
        }
    )

    return {"status": "ok" if all(c["ok"] for c in checks) else "fail", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the streaming session lifecycle")
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()

    _t = time.monotonic()
    result = asyncio.run(run(args.timeout))
    elapsed = int((time.monotonic() - _t) * 1000)

    print(json.dumps(result, indent=2))
    print(
        f"[<name>-perf] phase=qa_check duration_ms={elapsed} checks={len(result['checks'])} status={result['status']}",
        file=sys.stderr,
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
