#!/usr/bin/env python3
"""End-to-end check for <name> (shape: audio).

Runs the full synthesis pipeline offline — generate, encode, write, read,
decode, measure — with no model, no GPU and no API key, and asserts the
audio is actually audio.

Checks:

  1. produces_audio      — synthesis returns a non-empty buffer
  2. not_silent          — and it is above the silence floor
  3. duration_scales     — more text produces more audio
  4. sample_rate_honoured — the requested rate is the rate you get
  5. survives_round_trip — the signal is intact after encode and decode
  6. no_clipping         — the output is not driven into distortion
  7. deterministic       — the same text produces the same audio
  8. empty_input_rejected — empty text produces nothing, not silence
  9. detects_bad_audio   — the analyser actually fails on broken audio

**Check 2 is the reason this shape exists.** A synthesis endpoint that returns
HTTP 200 with a well-formed, entirely silent WAV passes every status check, every
"did we get bytes" check, and every health probe — and the user hears nothing.
Same family as zero discovered routes, zero exposed tools, zero extracted
records, zero frames.

Check 5 is its subtler sibling. A resampling or format bug leaves duration and
loudness perfectly plausible while shifting every frequency, so the audio plays
back as a chipmunk. Only measuring the signal itself catches it — the synthetic
engine gives each word a known pitch precisely so this is possible.

Check 9 exists because a checker that cannot fail proves nothing: it feeds the
analyser silence, emptiness and NaN, and requires each to be reported.

Usage:
    python3 qa_check.py
    python3 qa_check.py --base-url http://127.0.0.1:<PORT>   # also probe a live service

Exit codes:
    0  every check passed
    1  a check failed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import numpy as np

from audio_checks import SILENCE_RMS, analyse, analyse_bytes, encode
from engines import SyntheticEngine

SAMPLE_RATE = 22050


def run(base_url: str | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    engine = SyntheticEngine()

    # 1 & 2. There must be audio, and it must be audible.
    samples = engine.synthesize("the quick brown fox jumps over the lazy dog", SAMPLE_RATE)
    stats = analyse(samples, SAMPLE_RATE)
    checks.append(
        {
            "name": "produces_audio",
            "ok": not stats.is_empty,
            "detail": f"{stats.samples} samples, {stats.duration_s:.2f}s" if not stats.is_empty else "synthesis returned an empty buffer",
        }
    )
    checks.append(
        {
            "name": "not_silent",
            "ok": not stats.is_silent,
            "detail": f"rms {stats.rms:.4f} (floor {SILENCE_RMS:.0e})"
            + ("" if not stats.is_silent else " — a valid, well-formed file that nobody can hear, which every status check would call success"),
        }
    )

    # 3. Longer text must produce longer audio. Catches an engine that
    #    silently truncates, or returns a fixed-length buffer regardless.
    short = analyse(engine.synthesize("one", SAMPLE_RATE), SAMPLE_RATE)
    long = analyse(engine.synthesize("one two three four five six", SAMPLE_RATE), SAMPLE_RATE)
    checks.append(
        {
            "name": "duration_scales",
            "ok": long.duration_s > short.duration_s * 2,
            "detail": f"1 word {short.duration_s:.2f}s -> 6 words {long.duration_s:.2f}s" + ("" if long.duration_s > short.duration_s * 2 else " — output length ignores input"),
        }
    )

    # 4. The requested sample rate is what comes back.
    rate_problems = []
    for rate in (16000, 22050, 44100):
        got = analyse(engine.synthesize("hello world", rate), rate)
        if got.sample_rate != rate:
            rate_problems.append(f"asked {rate}, got {got.sample_rate}")
        # Duration must be rate-independent, or the engine is emitting a fixed
        # sample count and the audio speeds up as the rate rises.
        if not (0.5 < got.duration_s < 1.5):
            rate_problems.append(f"{rate}Hz produced {got.duration_s:.2f}s for 2 words")
    checks.append(
        {
            "name": "sample_rate_honoured",
            "ok": not rate_problems,
            "detail": "16k/22k/44.1k all honoured, duration rate-independent" if not rate_problems else "; ".join(rate_problems),
        }
    )

    # 5. The signal survives encoding and decoding intact.
    word = "verification"
    expected_hz = SyntheticEngine.frequency_for(word)
    decoded = analyse_bytes(encode(engine.synthesize(word, SAMPLE_RATE), SAMPLE_RATE))
    # A generous tolerance: FFT resolution over a short clip is coarse, and a
    # real resampling bug shifts the pitch by a large ratio, not a few hertz.
    drift = abs(decoded.dominant_hz - expected_hz)
    checks.append(
        {
            "name": "survives_round_trip",
            "ok": drift < 15.0 and decoded.sample_rate == SAMPLE_RATE,
            "detail": f"expected {expected_hz:.1f}Hz, decoded {decoded.dominant_hz:.1f}Hz "
            f"(drift {drift:.1f})" + ("" if drift < 15.0 else " — the signal shifted through encode/decode, which is what a resampling bug sounds like while duration and loudness stay plausible"),
        }
    )

    # 6. Not driven into distortion.
    checks.append(
        {
            "name": "no_clipping",
            "ok": stats.clipped_fraction < 0.01 and stats.peak <= 1.0,
            "detail": f"peak {stats.peak:.3f}, clipped {stats.clipped_fraction:.2%}",
        }
    )

    # 7. Determinism — required for caching, for reproducible tests, and for
    #    a regression in output being detectable at all.
    a = engine.synthesize("consistency matters", SAMPLE_RATE)
    b = engine.synthesize("consistency matters", SAMPLE_RATE)
    checks.append(
        {
            "name": "deterministic",
            "ok": np.array_equal(a, b),
            "detail": "same text produces identical audio" if np.array_equal(a, b) else "same text produced different audio — output cannot be cached or regression-tested",
        }
    )

    # 8. Empty input must produce nothing, rather than silence dressed as audio.
    empty = analyse(engine.synthesize("   ", SAMPLE_RATE), SAMPLE_RATE)
    checks.append(
        {
            "name": "empty_input_rejected",
            "ok": empty.is_empty,
            "detail": "empty text produces no samples" if empty.is_empty else f"empty text produced {empty.samples} samples of silence, which a caller cannot distinguish from real output",
        }
    )

    # 9. The analyser must actually fail on broken audio.
    silence = analyse(np.zeros(SAMPLE_RATE, dtype=np.float32), SAMPLE_RATE)
    nothing = analyse(np.zeros(0, dtype=np.float32), SAMPLE_RATE)
    nan_audio = analyse(np.full(1000, np.nan, dtype=np.float32), SAMPLE_RATE)
    loud = analyse(np.ones(SAMPLE_RATE, dtype=np.float32), SAMPLE_RATE)
    detects = bool(silence.problems()) and bool(nothing.problems()) and bool(nan_audio.problems()) and bool(loud.problems())
    checks.append(
        {
            "name": "detects_bad_audio",
            "ok": detects,
            "detail": "silence, emptiness, NaN and clipping are all reported" if detects else "the analyser passed audio it should have rejected — none of its other results mean anything",
        }
    )

    # Optional: probe a running service, which exercises the HTTP layer too.
    if base_url:
        try:
            import httpx

            response = httpx.post(
                f"{base_url.rstrip('/')}/synthesize",
                json={"text": "live service probe"},
                timeout=30,
            )
            served = analyse_bytes(response.content) if response.status_code == 200 else None
            checks.append(
                {
                    "name": "live_service",
                    "ok": served is not None and not served.is_silent,
                    "detail": f"{response.status_code}, {served.duration_s:.2f}s, rms {served.rms:.4f}" if served else f"{response.status_code}: {response.text[:120]}",
                }
            )
        except Exception as exc:
            checks.append({"name": "live_service", "ok": False, "detail": f"{type(exc).__name__}: {exc}"})

    return {"status": "ok" if all(c["ok"] for c in checks) else "fail", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the audio pipeline")
    parser.add_argument("--base-url", default=None, help="also probe a running service")
    args = parser.parse_args()

    _t = time.monotonic()
    result = run(args.base_url)
    elapsed = int((time.monotonic() - _t) * 1000)

    print(json.dumps(result, indent=2))
    print(
        f"[<name>-perf] phase=qa_check duration_ms={elapsed} checks={len(result['checks'])} status={result['status']}",
        file=sys.stderr,
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
