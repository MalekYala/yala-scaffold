"""Shape-specific configuration for <name> (shape: audio)."""

from __future__ import annotations

from config import Field, as_int

FIELDS: list[Field] = [
    Field(
        "TTS_PROVIDER",
        "Which speech engine to use. The scaffold ships 'synthetic' — real, "
        "audible, deterministic audio with no model — so the whole pipeline is "
        "verifiable before you wire in a real engine. See engines.py.",
        default="synthetic",
        section="Speech engine",
    ),
    Field(
        "TTS_MODEL",
        "Model or voice identifier, once a real engine is wired in.",
        default="",
    ),
    Field(
        "TTS_API_KEY",
        "Provider key. Prefer the Vault add-on over pasting it here.",
        commented=True,
        secret=True,
    ),
    Field(
        "SAMPLE_RATE",
        "Output sample rate in Hz. Mismatched rates are the classic silent bug: the audio plays, pitch- and speed-shifted, and every status check passes.",
        cast=as_int,
        default=22050,
        section="Audio",
    ),
    Field(
        "MAX_TEXT_CHARS",
        "Longest input accepted. Unbounded text means unbounded synthesis time and unbounded memory.",
        cast=as_int,
        default=5000,
    ),
]
