"""Audio synthesis service for <name>.

Shape: audio (speech/audio generation with verifiable output).

Endpoints:
    GET  /health          liveness
    POST /synthesize      text in, audio out
    POST /analyse         audio in, measurements out

`/synthesize` refuses to return silence. That is the whole point of this shape:
an engine that fails on an edge case typically returns an empty or silent
buffer, the HTTP layer wraps it in a perfectly valid 200, and the caller ships
a product where some inputs produce nothing audible. Checking the output before
returning it turns that into a 500 with a reason.
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import config
from audio_checks import analyse, analyse_bytes, encode
from engines import real_engine

settings = config.load()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>")

app = FastAPI(title="<name>", version=settings.app_version)
engine = real_engine(settings)


class SynthesisRequest(BaseModel):
    text: str
    sample_rate: int | None = None
    format: str = "WAV"


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "<name>",
        "version": settings.app_version,
        "engine": settings.tts_provider,
        "sample_rate": settings.sample_rate,
    }


@app.post("/synthesize")
def synthesize(body: SynthesisRequest) -> Response:
    """Generate audio, and verify it is audible before returning it."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    sample_rate = body.sample_rate or int(settings.sample_rate)
    started = time.perf_counter()
    samples = engine.synthesize(text, sample_rate)
    stats = analyse(samples, sample_rate)

    # The check that stops silence reaching a caller as a 200. An engine that
    # fails on an edge case returns an empty buffer, and without this the
    # service dutifully wraps nothing in a valid audio container.
    problems = stats.problems(expect_sample_rate=sample_rate)
    if problems:
        log.error(f"refusing to return unusable audio for {text[:60]!r}: {problems}")
        raise HTTPException(
            status_code=500,
            detail={"error": "engine produced unusable audio", "problems": problems},
        )

    payload = encode(samples, sample_rate, body.format)
    elapsed = (time.perf_counter() - started) * 1000
    log.info(f"[<name>-perf] phase=synthesize duration_ms={elapsed:.0f} chars={len(text)} audio_s={stats.duration_s:.2f} rms={stats.rms:.4f}")
    return Response(
        content=payload,
        media_type=f"audio/{body.format.lower()}",
        headers={
            # Surfaced as headers so a caller can assert on them without
            # decoding, and so a proxy log shows whether audio was real.
            "X-Audio-Duration-S": f"{stats.duration_s:.3f}",
            "X-Audio-Sample-Rate": str(stats.sample_rate),
            "X-Audio-RMS": f"{stats.rms:.6f}",
        },
    )


@app.post("/analyse")
async def analyse_endpoint(request: Request) -> JSONResponse:
    """Measure uploaded audio. Useful for checking someone else's output too."""
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="request body is empty")
    try:
        stats = analyse_bytes(payload)
    except Exception as exc:  # any decode failure is the caller's answer
        raise HTTPException(status_code=400, detail=f"could not decode audio: {exc}") from None
    return JSONResponse({"stats": stats.as_dict(), "problems": stats.problems()})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
