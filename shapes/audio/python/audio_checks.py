"""Audio analysis for <name>.

The measurements that tell you whether generated audio is actually audio.

An HTTP 200 with a well-formed WAV header proves almost nothing: the file can
be zero-length, entirely silent, at the wrong sample rate, clipped into
distortion, or full of NaN. Every one of those passes a status-code check and
a "did we get bytes back" check, and a user hears silence, a chipmunk, or a
buzz.

So this module answers the questions a listener would: is there sound, how
much, for how long, at what rate, and is it intact.

Pure functions over numpy arrays — no service, no network, no model — which is
what lets `qa_check.py` verify all of it offline in milliseconds.
"""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import soundfile as sf

#: Below this RMS, audio is silence for practical purposes. A generated clip
#: at this level is a failure however healthy the response looked.
SILENCE_RMS = 1e-4

#: Samples at or beyond full scale. A few are normal; a lot means the signal
#: was driven into distortion, which sounds broken but measures "loud".
CLIP_THRESHOLD = 0.999


@dataclass
class AudioStats:
    duration_s: float
    sample_rate: int
    channels: int
    samples: int
    rms: float
    peak: float
    clipped_fraction: float
    dominant_hz: float
    has_nan: bool

    @property
    def is_silent(self) -> bool:
        return self.rms < SILENCE_RMS

    @property
    def is_empty(self) -> bool:
        return self.samples == 0

    def problems(self, expect_sample_rate: int | None = None) -> list[str]:
        """Everything wrong with this audio, in the order a listener would notice."""
        found: list[str] = []
        if self.is_empty:
            found.append("zero samples — the response carried no audio at all")
            return found
        if self.has_nan:
            found.append("contains NaN or infinity — will click, pop, or crash a decoder")
        if self.is_silent:
            found.append(f"silent (rms {self.rms:.2e} < {SILENCE_RMS:.0e}) — a valid, well-formed file that nobody can hear")
        if self.clipped_fraction > 0.01:
            found.append(f"{self.clipped_fraction:.1%} of samples clipped — driven into distortion, which measures loud and sounds broken")
        if expect_sample_rate is not None and self.sample_rate != expect_sample_rate:
            found.append(f"sample rate {self.sample_rate} != requested {expect_sample_rate} — playback will be pitch- and speed-shifted")
        return found

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_silent"] = self.is_silent
        return data


def analyse(samples: np.ndarray, sample_rate: int) -> AudioStats:
    """Measure a float array of audio."""
    if samples.size == 0:
        return AudioStats(0.0, sample_rate, 0, 0, 0.0, 0.0, 0.0, 0.0, False)

    channels = 1 if samples.ndim == 1 else samples.shape[1]
    mono = samples if samples.ndim == 1 else samples.mean(axis=1)

    has_nan = bool(~np.isfinite(mono).all())
    finite = mono[np.isfinite(mono)] if has_nan else mono
    if finite.size == 0:
        return AudioStats(0.0, sample_rate, channels, 0, 0.0, 0.0, 0.0, 0.0, True)

    rms = float(np.sqrt(np.mean(finite.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(finite)))
    clipped = float(np.mean(np.abs(finite) >= CLIP_THRESHOLD))

    # Dominant frequency, for verifying a signal survived the pipeline intact.
    # A resampling or format bug shifts this, while duration and RMS stay
    # perfectly plausible.
    spectrum = np.abs(np.fft.rfft(finite))
    freqs = np.fft.rfftfreq(finite.size, 1.0 / sample_rate)
    dominant = float(freqs[int(np.argmax(spectrum))]) if spectrum.size else 0.0

    return AudioStats(
        duration_s=finite.size / float(sample_rate),
        sample_rate=sample_rate,
        channels=channels,
        samples=int(finite.size),
        rms=rms,
        peak=peak,
        clipped_fraction=clipped,
        dominant_hz=dominant,
        has_nan=has_nan,
    )


def analyse_bytes(payload: bytes) -> AudioStats:
    """Measure an encoded audio file (WAV, FLAC, OGG — whatever libsndfile reads)."""
    if not payload:
        return AudioStats(0.0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, False)
    samples, sample_rate = sf.read(io.BytesIO(payload), dtype="float32", always_2d=False)
    return analyse(samples, sample_rate)


def encode(samples: np.ndarray, sample_rate: int, fmt: str = "WAV") -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format=fmt, subtype="PCM_16" if fmt == "WAV" else None)
    return buffer.getvalue()
