"""Sandboxed image-to-image web interface for <name>."""

from __future__ import annotations

import io
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, Final

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

import config

# Validated at import, or the process does not start. The upload limits below
# are security controls, not tuning knobs — see config_extra.py.
settings = config.load()


def _brand() -> dict[str, Any]:
    """Read brand/config.json, falling back to built-in defaults.

    brand/ is the single place this project's identity is declared, so the
    interface reads it rather than hardcoding a title and a palette. A missing
    or malformed file degrades to defaults instead of failing the service:
    the wrong shade of blue is not worth a 500.
    """
    path = Path(__file__).resolve().parent / "brand" / "config.json"
    defaults: dict[str, Any] = {
        "display_name": "<name>",
        "colors": {
            "primary": "#2563eb",
            "background": "#111827",
            "surface": "#1f2937",
            "text": "#f9fafb",
            "border": "#4b5563",
        },
    }
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    colors = {**defaults["colors"], **(loaded.get("colors") or {})}
    return {
        "display_name": loaded.get("display_name") or defaults["display_name"],
        "colors": colors,
    }


BRAND: Final = _brand()

MAX_UPLOAD_BYTES: Final = settings.max_upload_bytes
MAX_IMAGE_PIXELS: Final = settings.max_image_pixels
MAX_OUTPUT_DIMENSION: Final = settings.max_output_dimension
ALLOWED_EFFECTS: Final = {"enhance", "grayscale", "blur", "edges", "invert"}

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

app = FastAPI(title="<name>", version=settings.app_version)


@app.middleware("http")
async def security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    # The version is part of the response on purpose: during an incident the
    # question is almost never "is something running" but "*which build* is
    # running".
    return {
        "status": "ok",
        "service": "<name>",
        "version": settings.app_version,
        "env": settings.env,
    }


@app.get("/", response_class=HTMLResponse)
def interface() -> str:
    """Render the interface with this project's brand tokens substituted in.

    Sentinel replacement rather than str.format(): the page embeds JavaScript
    template literals and CSS braces, and a format call would choke on both.
    """
    colors = BRAND["colors"]
    page = _PAGE
    for token, value in (
        ("__BRAND_NAME__", BRAND["display_name"]),
        ("__COLOR_PRIMARY__", colors["primary"]),
        ("__COLOR_BACKGROUND__", colors["background"]),
        ("__COLOR_SURFACE__", colors["surface"]),
        ("__COLOR_TEXT__", colors["text"]),
        ("__COLOR_BORDER__", colors["border"]),
    ):
        page = page.replace(token, str(value))
    return page


_PAGE: Final = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>__BRAND_NAME__ image-to-image</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: system-ui, sans-serif;
      --color-primary: __COLOR_PRIMARY__;
      --color-background: __COLOR_BACKGROUND__;
      --color-surface: __COLOR_SURFACE__;
      --color-text: __COLOR_TEXT__;
      --color-border: __COLOR_BORDER__;
    }
    body { margin: 0; background: var(--color-background); color: var(--color-text); }
    main { max-width: 1000px; margin: auto; padding: 2rem 1rem; }
    form { display: grid; gap: 1rem; padding: 1.25rem; background: var(--color-surface); border-radius: 12px; }
    .controls { display: grid; grid-template-columns: 1fr 1fr auto; gap: 1rem; align-items: end; }
    label { display: grid; gap: .35rem; }
    input, select, button { font: inherit; padding: .7rem; border-radius: 8px; border: 1px solid var(--color-border); }
    button { background: var(--color-primary); color: white; border: 0; cursor: pointer; }
    button:disabled { opacity: .6; cursor: wait; }
    .images { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 1.5rem; }
    figure { margin: 0; padding: 1rem; background: var(--color-surface); border-radius: 12px; min-height: 240px; }
    img { display: block; width: 100%; max-height: 60vh; object-fit: contain; margin-top: .75rem; }
    #status { min-height: 1.5rem; }
    @media (max-width: 700px) { .controls, .images { grid-template-columns: 1fr; } }
  </style>
</head>
<body><main>
  <h1>__BRAND_NAME__ &middot; Image-to-image interface</h1>
  <p>Uploads are processed locally in the sandbox and are not retained.</p>
  <form id="form">
    <label>Source image <input id="file" name="file" type="file" accept="image/png,image/jpeg,image/webp" required></label>
    <div class="controls">
      <label>Transform
        <select name="effect">
          <option value="enhance">Enhance</option><option value="grayscale">Grayscale</option>
          <option value="blur">Blur</option><option value="edges">Edges</option><option value="invert">Invert</option>
        </select>
      </label>
      <label>Strength <input name="strength" type="range" min="0" max="1" value=".6" step=".05"></label>
      <button id="submit" type="submit">Transform</button>
    </div>
    <div id="status" role="status"></div>
  </form>
  <section class="images">
    <figure><figcaption>Input</figcaption><img id="input" alt="Input preview"></figure>
    <figure><figcaption>Output · <a id="download" hidden download="transformed.png">download PNG</a></figcaption><img id="output" alt="Output preview"></figure>
  </section>
</main>
<script>
const form = document.querySelector('#form');
const file = document.querySelector('#file');
const input = document.querySelector('#input');
const output = document.querySelector('#output');
const status = document.querySelector('#status');
const submit = document.querySelector('#submit');
const download = document.querySelector('#download');
let inputUrl, outputUrl;
file.addEventListener('change', () => {
  if (inputUrl) URL.revokeObjectURL(inputUrl);
  inputUrl = file.files[0] ? URL.createObjectURL(file.files[0]) : '';
  input.src = inputUrl;
});
form.addEventListener('submit', async (event) => {
  event.preventDefault(); submit.disabled = true; status.textContent = 'Processing...';
  try {
    const response = await fetch('/api/transform', { method: 'POST', body: new FormData(form) });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${response.status})`);
    }
    if (outputUrl) URL.revokeObjectURL(outputUrl);
    outputUrl = URL.createObjectURL(await response.blob());
    output.src = outputUrl; download.href = outputUrl; download.hidden = false;
    status.textContent = 'Done.';
  } catch (error) { status.textContent = error.message; }
  finally { submit.disabled = false; }
});
</script></body></html>"""


def transform_image(image: Image.Image, effect: str, strength: float) -> Image.Image:
    """Apply a bounded, deterministic transform to a normalized RGB image."""
    if effect not in ALLOWED_EFFECTS:
        raise ValueError(f"unsupported effect: {effect}")
    strength = min(max(strength, 0.0), 1.0)
    source = ImageOps.exif_transpose(image).convert("RGB")
    source.thumbnail((MAX_OUTPUT_DIMENSION, MAX_OUTPUT_DIMENSION), Image.Resampling.LANCZOS)

    if effect == "enhance":
        result = ImageEnhance.Color(source).enhance(1.0 + strength)
        result = ImageEnhance.Contrast(result).enhance(1.0 + strength * 0.5)
        return ImageEnhance.Sharpness(result).enhance(1.0 + strength)
    if effect == "grayscale":
        target = ImageOps.grayscale(source).convert("RGB")
    elif effect == "blur":
        target = source.filter(ImageFilter.GaussianBlur(radius=1.0 + strength * 7.0))
    elif effect == "edges":
        target = ImageOps.autocontrast(source.filter(ImageFilter.FIND_EDGES))
    else:
        target = ImageOps.invert(source)
    return Image.blend(source, target, strength)


@app.post("/api/transform")
async def transform(
    file: Annotated[UploadFile, File()],
    effect: Annotated[str, Form()] = "enhance",
    strength: Annotated[float, Form(ge=0.0, le=1.0)] = 0.6,
) -> Response:
    if effect not in ALLOWED_EFFECTS:
        raise HTTPException(status_code=422, detail="Unsupported transform")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds upload limit")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            result = transform_image(opened, effect, strength)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=415, detail="Invalid or unsupported image") from exc

    output = io.BytesIO()
    result.save(output, format="PNG", optimize=True)
    return Response(
        output.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="transformed.png"'},
    )
