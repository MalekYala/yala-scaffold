"""Media sources for <name>.

The track is a **parameter**, not a hardcoded device. `SyntheticTrack`
generates frames procedurally, which is what lets the whole streaming path —
offer/answer, ICE, DTLS, encode, decode — be tested with no camera, no media
file, no GPU and no external service.

Swap it for whatever you are actually streaming: a screen capture, a camera, a
rendered viewport, frames arriving from another process. `build_track()` is the
one place that decision lives, so nothing downstream has to know.

The same reasoning appears elsewhere in this kit: the `agent` shape takes its
model as a parameter so the graph can be exercised offline. A pipeline that can
only be tested against real hardware is, in practice, a pipeline nobody tests.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from aiortc import VideoStreamTrack
from av import VideoFrame


class SyntheticTrack(VideoStreamTrack):
    """Procedurally generated video. Deterministic in shape, animated in content.

    Each frame carries a moving gradient and a frame counter baked into the pixel
    values, so a receiver can prove it is getting *new* frames rather than the
    same one repeatedly — a real failure mode when a source stalls but the
    connection stays up.
    """

    kind = "video"

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30) -> None:
        super().__init__()
        self.width = width
        self.height = height
        self.fps = fps
        self.frames_sent = 0

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()

        array = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        # A channel that changes every frame: a receiver comparing consecutive
        # frames can tell "stream is live" from "stream is frozen".
        array[:, :, 0] = (self.frames_sent * 7) % 256
        array[:, :, 1] = np.linspace(0, 255, self.width, dtype=np.uint8)[None, :]
        array[:, :, 2] = np.linspace(0, 255, self.height, dtype=np.uint8)[:, None]

        frame = VideoFrame.from_ndarray(array, format="rgb24")
        frame.pts = pts
        frame.time_base = time_base
        self.frames_sent += 1
        return frame


class StalledTrack(SyntheticTrack):
    """Sends a fixed number of frames, then stops producing.

    Exists so `qa_check.py` can prove the freeze detector works. A source that
    stalls while the peer connection stays happily "connected" is the failure
    that looks most like success — every connection-level metric is green and
    the viewer sees a still image.
    """

    def __init__(self, stall_after: int = 3, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.stall_after = stall_after

    async def recv(self) -> VideoFrame:
        if self.frames_sent >= self.stall_after:
            # Never returns. Mirrors a wedged capture device rather than a
            # clean end-of-stream, which is the harder case to detect.
            import asyncio

            await asyncio.sleep(3600)
        return await super().recv()


def build_track(settings: Any = None) -> VideoStreamTrack:
    """The single place the media source is chosen.

    Replace the body for a real source, e.g.:

        from aiortc.contrib.media import MediaPlayer
        return MediaPlayer("/dev/video0", format="v4l2").video

    Keeping this a function rather than a module-level object matters: tracks
    are stateful and single-use, so each peer connection needs its own.
    """
    if settings is None:
        return SyntheticTrack()
    return SyntheticTrack(
        width=int(settings.video_width),
        height=int(settings.video_height),
        fps=int(settings.video_fps),
    )
