"""Signalling and streaming server for <name>.

Exposes a WHIP-style endpoint: a client POSTs an SDP offer, gets an SDP answer,
and media flows. That is the whole signalling protocol — deliberately, because
signalling is the part every project reinvents and the part that has no standard
worth inventing again.

Endpoints:
    GET  /health   liveness — is the process up?
    GET  /ready    readiness — are sessions actually carrying media?
    POST /offer    SDP offer in, SDP answer out
    GET  /stats    per-session frame counts and freshness

/health and /ready answer different questions on purpose. A streaming server
with every session frozen is alive and useless; conflating the two means either
being restarted for nothing or reporting healthy while nobody can see anything.
"""

from __future__ import annotations

import logging
import time

from aiortc import RTCSessionDescription
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import config
from session import PeerSession
from tracks import build_track

settings = config.load()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>")

app = FastAPI(title="<name>", version=settings.app_version)

SESSIONS: dict[str, PeerSession] = {}


class Offer(BaseModel):
    sdp: str
    type: str = "offer"


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness only. Deliberately says nothing about whether media flows."""
    return {
        "status": "ok",
        "service": "<name>",
        "version": settings.app_version,
        "sessions": len(SESSIONS),
    }


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness: is anything actually being delivered?

    With no sessions this reports ok — an idle server is healthy, not broken.
    With sessions that have all stalled it reports degraded, because that is a
    server which looks perfectly fine and shows viewers a still image.
    """
    stalled = [name for name, session in SESSIONS.items() if session.stats.is_stalled(float(settings.stall_timeout_s))]
    detail = {
        "service": "<name>",
        "sessions": len(SESSIONS),
        "stalled": stalled,
    }
    if SESSIONS and len(stalled) == len(SESSIONS):
        detail["status"] = "degraded"
        detail["reason"] = "every session has stopped delivering frames"
        return JSONResponse(detail, status_code=503)
    detail["status"] = "ok"
    return JSONResponse(detail, status_code=200)


@app.post("/offer")
async def offer(body: Offer) -> dict[str, str]:
    """Accept a browser's offer and answer it with a media track."""
    session = PeerSession(
        ice_urls=settings.ice_servers,
        track_factory=lambda: build_track(settings),
        stall_timeout_s=float(settings.stall_timeout_s),
    )
    started = time.perf_counter()
    answer = await session.accept(RTCSessionDescription(sdp=body.sdp, type=body.type))

    session_id = f"s{len(SESSIONS) + 1}-{int(time.time())}"
    SESSIONS[session_id] = session
    log.info(f"[<name>-perf] phase=negotiate duration_ms={(time.perf_counter() - started) * 1000:.0f} session={session_id}")
    return {"sdp": answer.sdp, "type": answer.type, "session": session_id}


@app.get("/stats")
def stats() -> dict[str, object]:
    """Per-session truth: frames, freshness, reconnects."""
    now = time.monotonic()
    return {
        "sessions": {
            name: {
                "frames_sent": session.stats.frames_sent,
                "frames_received": session.stats.frames_received,
                "flowing": session.stats.is_flowing,
                "seconds_since_frame": round(now - session.stats.last_frame_at, 2) if session.stats.last_frame_at else None,
                "reconnects": session.stats.reconnects,
            }
            for name, session in SESSIONS.items()
        }
    }


@app.get("/", response_class=HTMLResponse)
def viewer() -> str:
    """A minimal browser client, so the stream is watchable without extra tooling."""
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title><name> stream</title>
<style>
 body{margin:0;background:#111827;color:#f9fafb;font-family:system-ui,sans-serif}
 main{max-width:900px;margin:auto;padding:2rem 1rem}
 video{width:100%;background:#000;border-radius:12px}
 button{font:inherit;padding:.7rem 1.2rem;border:0;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer}
 #status{min-height:1.5rem;margin-top:.75rem}
</style></head>
<body><main>
  <h1><name></h1>
  <p>WebRTC stream. Press play to negotiate a session.</p>
  <video id="v" autoplay playsinline muted></video>
  <p><button id="go">Start stream</button></p>
  <div id="status" role="status"></div>
<script>
const v = document.querySelector('#v'), status = document.querySelector('#status');
document.querySelector('#go').addEventListener('click', async () => {
  status.textContent = 'negotiating…';
  const pc = new RTCPeerConnection();
  pc.addTransceiver('video', { direction: 'recvonly' });
  pc.ontrack = (e) => { v.srcObject = e.streams[0]; status.textContent = 'streaming'; };
  pc.oniceconnectionstatechange = () => { status.textContent = pc.iceConnectionState; };
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  // Wait for ICE gathering so the offer carries its candidates.
  await new Promise((r) => {
    if (pc.iceGatheringState === 'complete') return r();
    pc.onicegatheringstatechange = () => pc.iceGatheringState === 'complete' && r();
  });
  const res = await fetch('/offer', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type }),
  });
  if (!res.ok) { status.textContent = 'negotiation failed'; return; }
  await pc.setRemoteDescription(await res.json());
});
</script></main></body></html>"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
