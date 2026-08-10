"""Peer session lifecycle for <name>.

Shape: stream (WebRTC media/data streaming).

This is where streaming projects actually break. The happy path — offer,
answer, connected — is the easy part and the part everyone tests. What fails in
production is everything after: a network blip, a NAT rebind, a peer that goes
away without saying goodbye, a source that wedges while the connection stays
green.

So this module owns four things, and `qa_check.py` holds it to all of them:

  connect    offer/answer exchange and ICE
  observe    are bytes actually moving, or is it merely "connected"?
  reconnect  bounded exponential backoff, not a tight retry loop
  teardown   release the peer connection and its tasks, every time

A note on ICE servers
---------------------
`ICE_SERVERS` is empty by default. Loopback and LAN connections need no STUN,
and the default public STUN servers turn a 1.3-second local handshake into a
15-second one when they are unreachable — which is exactly what happens in CI
and in a sandbox. Configure real STUN/TURN for production, where peers are
actually behind NATs; leave it empty for tests, or the suite becomes slow
enough that people stop running it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)

log = logging.getLogger("<name>")


def ice_configuration(urls: str = "") -> RTCConfiguration:
    """Build ICE config from a comma-separated URL list. Empty means no STUN."""
    servers = [RTCIceServer(urls=url.strip()) for url in (urls or "").split(",") if url.strip()]
    return RTCConfiguration(iceServers=servers)


@dataclass
class SessionStats:
    """What actually happened, as opposed to what state the connection claims."""

    connected_at: float | None = None
    bytes_received: int = 0
    frames_received: int = 0
    #: Outbound frames. A send-only server never *receives* anything, so
    #: counting only the inbound direction reports every healthy broadcast as
    #: dead. Both directions matter, and which one applies depends on the role.
    frames_sent: int = 0
    reconnects: int = 0
    last_frame_at: float | None = None
    ice_states: list[str] = field(default_factory=list)
    connection_states: list[str] = field(default_factory=list)

    @property
    def is_flowing(self) -> bool:
        """True only if something actually crossed the wire, in either direction.

        A session can report `connected` with zero frames — a codec mismatch,
        a track that was never added, a source that failed to start. Every
        connection-level metric is green and the viewer sees nothing. Treating
        `connected` as success is the vacuous pass this shape exists to refuse.
        """
        return self.frames_received > 0 or self.frames_sent > 0 or self.bytes_received > 0

    def is_stalled(self, timeout_s: float) -> bool:
        """True when frames moved once and then stopped.

        Never having moved is not stalled — that is the `is_flowing` failure,
        which has a different cause and a different fix. Conflating them sends
        you looking at the network when the track was never added.
        """
        if self.last_frame_at is None:
            return False
        return (time.monotonic() - self.last_frame_at) > timeout_s


class PeerSession:
    """One peer connection, with its lifecycle made observable and testable."""

    def __init__(
        self,
        ice_urls: str = "",
        track_factory: Callable[[], Any] | None = None,
        stall_timeout_s: float = 5.0,
    ) -> None:
        self.ice_urls = ice_urls
        self.track_factory = track_factory
        self.stall_timeout_s = stall_timeout_s
        self.pc: RTCPeerConnection | None = None
        self.stats = SessionStats()
        self.outbound_track: Any = None
        self._tasks: set[asyncio.Task[None]] = set()

    def _watch_outbound(self, track: Any) -> None:
        """Mirror the outbound track's counter into stats.

        aiortc gives no send-side callback, so a sender otherwise has no way
        to answer "am I actually producing frames?" — and a broadcast server
        that reports itself dead while streaming perfectly is worse than no
        metric at all.
        """
        self.outbound_track = track

        async def poll() -> None:
            while True:
                sent = getattr(track, "frames_sent", 0)
                if sent > self.stats.frames_sent:
                    self.stats.frames_sent = sent
                    self.stats.last_frame_at = time.monotonic()
                await asyncio.sleep(0.25)

        task = asyncio.ensure_future(poll())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ── connect ────────────────────────────────────────────────────────────

    def _new_peer_connection(self) -> RTCPeerConnection:
        pc = RTCPeerConnection(ice_configuration(self.ice_urls))

        @pc.on("iceconnectionstatechange")
        async def on_ice() -> None:
            self.stats.ice_states.append(pc.iceConnectionState)
            log.info(f"[<name>-perf] phase=ice_state state={pc.iceConnectionState}")

        @pc.on("connectionstatechange")
        async def on_connection() -> None:
            self.stats.connection_states.append(pc.connectionState)
            if pc.connectionState == "connected" and self.stats.connected_at is None:
                self.stats.connected_at = time.monotonic()

        @pc.on("track")
        def on_track(track: Any) -> None:
            # Count what arrives. Without this the session can only report
            # what state it is in, never whether it is doing anything.
            task = asyncio.ensure_future(self._consume(track))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        return pc

    async def _consume(self, track: Any) -> None:
        try:
            while True:
                frame = await track.recv()
                self.stats.frames_received += 1
                self.stats.last_frame_at = time.monotonic()
                size = getattr(frame, "width", 0) * getattr(frame, "height", 0)
                self.stats.bytes_received += size
        except Exception:  # a closed track ends the loop normally
            return

    async def offer(self) -> RTCSessionDescription:
        """Create the local offer, adding the outbound track if there is one."""
        self.pc = self._new_peer_connection()
        if self.track_factory is not None:
            # A fresh track per connection: tracks are stateful and single-use,
            # so reusing one across reconnects silently produces no media.
            track = self.track_factory()
            self.pc.addTrack(track)
            self._watch_outbound(track)
        await self.pc.setLocalDescription(await self.pc.createOffer())
        return self.pc.localDescription

    async def accept(self, offer: RTCSessionDescription) -> RTCSessionDescription:
        """Answer a remote offer."""
        self.pc = self._new_peer_connection()
        await self.pc.setRemoteDescription(offer)
        if self.track_factory is not None:
            track = self.track_factory()
            self.pc.addTrack(track)
            self._watch_outbound(track)
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        return self.pc.localDescription

    async def complete(self, answer: RTCSessionDescription) -> None:
        if self.pc is None:
            raise RuntimeError("no peer connection: call offer() first")
        await self.pc.setRemoteDescription(answer)

    async def wait_until_flowing(self, timeout_s: float = 20.0) -> bool:
        """Wait for actual media in either direction, not merely a connected state."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.stats.is_flowing:
                return True
            await asyncio.sleep(0.05)
        return False

    # ── teardown ───────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release the connection and every task it spawned.

        Leaked consumer tasks are why a long-running streaming service grows a
        file descriptor at a time until it falls over days later, with nothing
        in the logs pointing at the cause.
        """
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        if self.pc is not None:
            await self.pc.close()
            self.pc = None


async def connect_with_backoff(
    connect: Callable[[], Any],
    attempts: int = 5,
    base_delay_s: float = 0.2,
    max_delay_s: float = 10.0,
) -> Any:
    """Retry a connection with bounded exponential backoff.

    Bounded, and exponential, on purpose. A tight retry loop against a peer
    that is down is indistinguishable from an attack, and gets you rate-limited
    or blocked precisely when you are trying to recover. The cap stops the
    delay growing until reconnection is effectively never.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await connect()
        except Exception as exc:  # the point is to survive these
            last_error = exc
            if attempt == attempts:
                break
            delay = min(base_delay_s * (2 ** (attempt - 1)), max_delay_s)
            log.warning(f"connect attempt {attempt}/{attempts} failed ({type(exc).__name__}); retrying in {delay:.1f}s")
            await asyncio.sleep(delay)
    raise RuntimeError(f"could not connect after {attempts} attempt(s): {last_error}")
