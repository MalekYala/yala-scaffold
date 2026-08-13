"""Shape-specific configuration for <name> (shape: stream)."""

from __future__ import annotations

from config import Field, as_int

FIELDS: list[Field] = [
    Field(
        "ICE_SERVERS",
        "Comma-separated STUN/TURN URLs. EMPTY BY DEFAULT on purpose: loopback "
        "and LAN peers need no STUN, and unreachable public STUN turns a "
        "1.3-second local handshake into a 15-second one. Configure real "
        "servers for production, where peers are actually behind NATs.",
        default="",
        section="WebRTC",
    ),
    Field(
        "STALL_TIMEOUT_S",
        "Seconds without a frame before a session counts as stalled. A wedged source with a live connection is the failure that looks most like success — every connection metric stays green.",
        default="5.0",
    ),
    Field(
        "VIDEO_WIDTH",
        "Frame width for the synthetic source.",
        cast=as_int,
        default=640,
        section="Media",
    ),
    Field("VIDEO_HEIGHT", "Frame height for the synthetic source.", cast=as_int, default=480),
    Field("VIDEO_FPS", "Target frames per second.", cast=as_int, default=30),
    Field(
        "MAX_SESSIONS",
        "Concurrent peer connections allowed. Each costs CPU for encoding; unbounded sessions is how a streaming box falls over.",
        cast=as_int,
        default=8,
    ),
]
