"""Tests for <name>'s streaming session lifecycle.

All against local peers with no STUN, so a full offer/answer/ICE/DTLS round
trip takes about a second. The same suite with default ICE servers takes
fifteen — which is the difference between a check that runs on every commit
and one people turn off.
"""

from __future__ import annotations

import asyncio
import itertools
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from session import PeerSession, SessionStats, connect_with_backoff, ice_configuration  # noqa: E402
from tracks import StalledTrack, SyntheticTrack  # noqa: E402


class TestIceConfiguration:
    def test_empty_means_no_servers(self):
        # The default. Loopback needs no STUN, and unreachable STUN is what
        # makes a local handshake take 15 seconds instead of 1.3.
        assert ice_configuration("").iceServers == []

    def test_parses_a_comma_separated_list(self):
        config = ice_configuration("stun:a.example:3478, stun:b.example:3478")
        assert config.iceServers is not None
        assert len(config.iceServers) == 2

    def test_ignores_blank_entries(self):
        servers = ice_configuration("stun:a.example:3478, ,").iceServers
        assert servers is not None
        assert len(servers) == 1


class TestSessionStats:
    def test_connected_with_nothing_received_is_not_flowing(self):
        # The vacuous success this shape exists to refuse: every
        # connection-level metric green, viewer sees nothing.
        assert not SessionStats().is_flowing

    def test_a_received_frame_counts_as_flowing(self):
        assert SessionStats(frames_received=1).is_flowing

    def test_never_receiving_is_not_stalled(self):
        # Nothing ever arrived, so there is no freshness to have lost. That is
        # the media_flows failure, not the stall failure — different causes,
        # different fixes.
        assert not SessionStats().is_stalled(timeout_s=0.1)

    def test_frames_that_stopped_are_stalled(self):
        stats = SessionStats(frames_received=5, last_frame_at=time.monotonic() - 10)
        assert stats.is_stalled(timeout_s=1.0)

    def test_recent_frames_are_not_stalled(self):
        stats = SessionStats(frames_received=5, last_frame_at=time.monotonic())
        assert not stats.is_stalled(timeout_s=1.0)


class TestBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_without_retrying(self):
        calls = []

        async def ok():
            calls.append(1)
            return "fine"

        assert await connect_with_backoff(ok, attempts=3, base_delay_s=0.01) == "fine"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_recovers_after_transient_failures(self):
        calls = []

        async def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("refused")
            return "fine"

        assert await connect_with_backoff(flaky, attempts=5, base_delay_s=0.01) == "fine"
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_gives_up_and_says_why(self):
        async def never():
            raise ConnectionError("refused")

        with pytest.raises(RuntimeError, match="could not connect"):
            await connect_with_backoff(never, attempts=3, base_delay_s=0.01)

    @pytest.mark.asyncio
    async def test_delays_grow_and_are_capped(self):
        # Exponential so a downed peer is not hammered; capped so recovery
        # does not recede into never.
        times = []

        async def failing():
            times.append(time.monotonic())
            raise ConnectionError("refused")

        with pytest.raises(RuntimeError):
            await connect_with_backoff(failing, attempts=4, base_delay_s=0.05, max_delay_s=0.12)

        gaps = [b - a for a, b in itertools.pairwise(times)]
        assert gaps[1] > gaps[0], f"delays must grow: {gaps}"
        assert max(gaps) <= 0.5, f"delay must stay capped: {gaps}"


class TestLoopbackSession:
    """Real peer connections. Slower than the unit tests, and worth it."""

    @pytest.mark.asyncio
    async def test_media_actually_flows(self):
        sender = PeerSession(track_factory=lambda: SyntheticTrack(width=160, height=120))
        receiver = PeerSession()
        try:
            await sender.complete(await receiver.accept(await sender.offer()))
            assert await receiver.wait_until_flowing(timeout_s=20)
            assert receiver.stats.frames_received > 0
        finally:
            await sender.close()
            await receiver.close()

    @pytest.mark.asyncio
    async def test_a_stalled_source_is_detected(self):
        sender = PeerSession(track_factory=lambda: StalledTrack(stall_after=2, width=160, height=120))
        receiver = PeerSession()
        try:
            await sender.complete(await receiver.accept(await sender.offer()))
            await receiver.wait_until_flowing(timeout_s=20)
            await asyncio.sleep(1.5)
            assert receiver.stats.frames_received > 0, "should deliver before stalling"
            assert receiver.stats.is_stalled(timeout_s=0.5)
        finally:
            await sender.close()
            await receiver.close()

    @pytest.mark.asyncio
    async def test_close_releases_the_connection_and_its_tasks(self):
        # Leaked consumer tasks are why a long-running streamer dies days
        # later with nothing in the logs pointing at the cause.
        sender = PeerSession(track_factory=lambda: SyntheticTrack(width=160, height=120))
        receiver = PeerSession()
        await sender.complete(await receiver.accept(await sender.offer()))
        await receiver.wait_until_flowing(timeout_s=20)

        await sender.close()
        await receiver.close()
        assert sender.pc is None and receiver.pc is None
        assert all(t.done() or t.cancelled() for t in receiver._tasks)
