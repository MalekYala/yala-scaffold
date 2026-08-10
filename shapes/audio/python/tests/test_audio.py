"""Tests for <name>'s audio analysis and synthesis.

Everything here is offline and model-free. The measurements are what decide
whether generated audio is usable, so they need to be right before anything
downstream can be trusted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from audio_checks import SILENCE_RMS, analyse, analyse_bytes, encode  # noqa: E402
from engines import SyntheticEngine  # noqa: E402

SR = 22050


def tone(hz: float, seconds: float = 1.0, amplitude: float = 0.4) -> np.ndarray:
    t = np.arange(int(seconds * SR), dtype=np.float32) / SR
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


class TestAnalyse:
    def test_measures_duration(self):
        assert analyse(tone(440, 2.0), SR).duration_s == pytest.approx(2.0, abs=0.01)

    def test_finds_the_dominant_frequency(self):
        assert analyse(tone(440), SR).dominant_hz == pytest.approx(440, abs=2)

    def test_silence_is_silent(self):
        stats = analyse(np.zeros(SR, dtype=np.float32), SR)
        assert stats.is_silent
        assert not stats.is_empty

    def test_empty_is_empty_but_not_merely_silent(self):
        # Different causes, different fixes: an empty buffer means the engine
        # returned nothing, silence means it returned the wrong thing.
        stats = analyse(np.zeros(0, dtype=np.float32), SR)
        assert stats.is_empty
        assert any("zero samples" in p for p in stats.problems())

    def test_real_audio_is_not_silent(self):
        assert not analyse(tone(440), SR).is_silent

    def test_detects_clipping(self):
        stats = analyse(np.ones(SR, dtype=np.float32) * 1.5, SR)
        assert stats.clipped_fraction > 0.9
        assert any("clipped" in p for p in stats.problems())

    def test_detects_nan(self):
        stats = analyse(np.full(1000, np.nan, dtype=np.float32), SR)
        assert stats.has_nan
        assert stats.problems()

    def test_reports_a_sample_rate_mismatch(self):
        problems = analyse(tone(440), SR).problems(expect_sample_rate=44100)
        assert any("sample rate" in p for p in problems)

    def test_clean_audio_has_no_problems(self):
        assert analyse(tone(440), SR).problems(expect_sample_rate=SR) == []

    def test_handles_stereo(self):
        stereo = np.stack([tone(440), tone(660)], axis=1)
        stats = analyse(stereo, SR)
        assert stats.channels == 2
        assert not stats.is_silent


class TestEncodeDecode:
    def test_round_trip_preserves_the_signal(self):
        # A resampling or format bug shifts pitch while leaving duration and
        # loudness perfectly plausible — this is the only check that sees it.
        decoded = analyse_bytes(encode(tone(440, 1.0), SR))
        assert decoded.sample_rate == SR
        assert decoded.dominant_hz == pytest.approx(440, abs=5)
        assert decoded.duration_s == pytest.approx(1.0, abs=0.01)

    def test_empty_payload_is_empty(self):
        assert analyse_bytes(b"").is_empty


class TestSyntheticEngine:
    engine = SyntheticEngine()

    def test_produces_audible_output(self):
        stats = analyse(self.engine.synthesize("hello world", SR), SR)
        assert not stats.is_silent
        assert stats.rms > SILENCE_RMS * 100

    def test_is_deterministic(self):
        a = self.engine.synthesize("same input", SR)
        b = self.engine.synthesize("same input", SR)
        assert np.array_equal(a, b)

    def test_different_text_sounds_different(self):
        a = self.engine.synthesize("alpha", SR)
        b = self.engine.synthesize("bravo", SR)
        assert not np.array_equal(a, b)

    def test_duration_scales_with_word_count(self):
        one = analyse(self.engine.synthesize("one", SR), SR).duration_s
        four = analyse(self.engine.synthesize("one two three four", SR), SR).duration_s
        assert four > one * 3

    def test_duration_is_independent_of_sample_rate(self):
        # If it is not, the engine is emitting a fixed sample count and the
        # audio speeds up as the rate rises.
        low = analyse(self.engine.synthesize("two words", 16000), 16000).duration_s
        high = analyse(self.engine.synthesize("two words", 44100), 44100).duration_s
        assert low == pytest.approx(high, abs=0.02)

    def test_empty_text_produces_nothing(self):
        assert self.engine.synthesize("   ", SR).size == 0

    def test_word_pitch_is_stable_and_recoverable(self):
        expected = SyntheticEngine.frequency_for("verification")
        got = analyse(self.engine.synthesize("verification", SR), SR).dominant_hz
        assert got == pytest.approx(expected, abs=15)

    def test_pitches_sit_in_the_speech_range(self):
        for word in ("alpha", "bravo", "charlie", "delta", "echo"):
            assert 120 <= SyntheticEngine.frequency_for(word) <= 360

    def test_output_does_not_clip(self):
        stats = analyse(self.engine.synthesize("loud words here", SR), SR)
        assert stats.peak <= 1.0
        assert stats.clipped_fraction == 0.0
