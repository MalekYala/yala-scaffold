"""Shape-specific configuration for <name> (shape: image).

The universal schema in `config.py` carries what every project needs. An
image-processing service also needs limits on what it will accept, and those
limits are load-bearing security controls rather than tuning knobs: they are
what stops a 40000x40000 PNG from turning into a memory-exhaustion bug.

Declaring them here rather than reading `os.environ` inline means they are
typed, validated at startup, and documented in `.env.example` automatically —
`config.py` picks this module up on its own.
"""

from __future__ import annotations

from config import Field, as_int

FIELDS: list[Field] = [
    Field(
        "MAX_UPLOAD_BYTES",
        "Largest upload accepted, in bytes. Rejected before the image is decoded, so an oversized file costs almost nothing.",
        cast=as_int,
        default=10 * 1024 * 1024,
        section="Image limits",
    ),
    Field(
        "MAX_IMAGE_PIXELS",
        "Pillow decompression-bomb guard: total pixels allowed after decoding. A small compressed file can still expand to gigabytes of bitmap.",
        cast=as_int,
        default=20000000,
    ),
    Field(
        "MAX_OUTPUT_DIMENSION",
        "Longest edge of the returned image. Larger inputs are scaled down, bounding both response size and processing time.",
        cast=as_int,
        default=2048,
    ),
]
