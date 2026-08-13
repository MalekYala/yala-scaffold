"""Speech engines for <name> — one real, one synthetic.

The engine is a **parameter**, not a hardcoded model. `SyntheticEngine`
produces real, non-silent, deterministic audio with no model, no GPU and no
API key, which is what lets the whole pipeline — generate, encode, write,
read, decode, measure — be verified on every commit.

It is not a stand-in for speech quality. It is a stand-in for *the pipeline
being intact*, which is what actually breaks: a resampling bug, a format
mismatch, an engine returning an empty buffer on an edge case. Those produce
silence or chipmunks regardless of how good the model is.

Same reasoning as the `agent` shape's scripted model and the `stream` shape's
synthetic track: push the part that needs a model or a GPU to the edge, and the
core stays verifiable.
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol

import numpy as np


class SpeechEngine(Protocol):
    """What every engine must provide."""

    def synthesize(self, text: str, sample_rate: int) -> np.ndarray: ...


class SyntheticEngine:
    """Deterministic, audible, model-free speech-shaped audio.

    Each word becomes a short tone whose pitch is derived from a hash of the
    word, with an envelope so it does not click, and a gap between words. The
    result is obviously not speech — but it has the properties that matter for
    checking a pipeline: non-silent, correct duration, correct sample rate, and
    a **recoverable** dominant frequency.

    That last property is what makes the round-trip check meaningful. The
    checker asks for a known word, then measures the returned audio's dominant
    frequency and confirms it matches what that word should produce. A
    resampling or format bug shifts it, while duration and RMS stay entirely
    plausible.
    """

    #: Seconds of tone per word, plus a gap. Roughly conversational pacing.
    WORD_SECONDS = 0.28
    GAP_SECONDS = 0.06
    AMPLITUDE = 0.35

    @staticmethod
    def frequency_for(word: str) -> float:
        """A stable pitch for a word, inside the range human speech occupies."""
        digest = hashlib.sha256(word.lower().strip().encode("utf-8")).digest()
        # 120-360 Hz: fundamental frequencies people actually produce, and well
        # clear of the resampling artefacts that live up near Nyquist.
        return 120.0 + (int.from_bytes(digest[:4], "big") % 2401) / 10.0

    def synthesize(self, text: str, sample_rate: int) -> np.ndarray:
        words = [w for w in text.split() if w.strip()]
        if not words:
            # An empty request must produce an empty result, not silence
            # dressed up as audio. The caller decides whether that is an error.
            return np.zeros(0, dtype=np.float32)

        chunks: list[np.ndarray] = []
        gap = np.zeros(int(self.GAP_SECONDS * sample_rate), dtype=np.float32)

        for word in words:
            count = int(self.WORD_SECONDS * sample_rate)
            t = np.arange(count, dtype=np.float32) / sample_rate
            frequency = self.frequency_for(word)
            tone = np.sin(2.0 * np.pi * frequency * t, dtype=np.float32)
            # A little second harmonic, so it reads as voice-like rather than
            # a test tone, without moving the dominant frequency.
            tone += 0.25 * np.sin(4.0 * np.pi * frequency * t, dtype=np.float32)
            # Raised-cosine envelope: a hard edge produces a click, which shows
            # up as broadband energy and muddies the dominant-frequency check.
            envelope = np.hanning(count).astype(np.float32)
            chunks.append(self.AMPLITUDE * tone * envelope)
            chunks.append(gap)

        return np.concatenate(chunks[:-1]).astype(np.float32)


def real_engine(settings: Any) -> SpeechEngine:
    """The production engine.

    Imported lazily so a project using only the synthetic engine pays for no
    provider SDK, and does not fail because a key is absent.

    Replace the body with whatever you actually synthesize with — Piper,
    Coqui, ElevenLabs, OpenAI, a local vLLM-served model. The only contract is
    `synthesize(text, sample_rate) -> float32 numpy array`.
    """
    provider = settings.tts_provider.lower()

    if provider == "synthetic":
        return SyntheticEngine()

    raise ValueError(
        f"unsupported TTS_PROVIDER={provider!r}. The scaffold ships 'synthetic' "
        f"only — wire your real engine into real_engine() in engines.py. Its "
        f"contract is synthesize(text, sample_rate) -> float32 numpy array."
    )
