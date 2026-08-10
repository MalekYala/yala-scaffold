"""End-to-end check for the image-to-image interface."""

from __future__ import annotations

import io
import json
import os
import sys
from typing import Any

import httpx
from PIL import Image


def run() -> dict[str, Any]:
    base = f"http://127.0.0.1:{os.environ.get('PORT', '<PORT>')}"
    checks: list[dict[str, Any]] = []

    health = httpx.get(f"{base}/health", timeout=5)
    checks.append({"name": "health", "ok": health.status_code == 200})

    interface = httpx.get(base, timeout=5)
    checks.append(
        {
            "name": "interface",
            "ok": interface.status_code == 200 and "Image-to-image interface" in interface.text,
        }
    )

    # The page is styled from brand/config.json. If that substitution silently
    # failed, the markup still returns 200 and still contains the heading —
    # it just renders with literal `__COLOR_PRIMARY__` as a colour value, which
    # every browser discards, leaving an unstyled page. HTTP status cannot see
    # that; an assertion on the rendered tokens can.
    rendered = interface.text
    checks.append(
        {
            "name": "brand_applied",
            "ok": ("__BRAND_NAME__" not in rendered and "__COLOR_" not in rendered and "--color-primary:" in rendered),
        }
    )

    source = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 60)).save(source, format="PNG")
    transformed = httpx.post(
        f"{base}/api/transform",
        files={"file": ("qa.png", source.getvalue(), "image/png")},
        data={"effect": "invert", "strength": "1"},
        timeout=10,
    )
    valid_png = False
    if transformed.status_code == 200:
        try:
            with Image.open(io.BytesIO(transformed.content)) as output:
                valid_png = output.format == "PNG" and output.size == (8, 8)
        except (OSError, Image.DecompressionBombError):
            valid_png = False
    checks.append({"name": "transform", "ok": valid_png})
    return {"status": "ok" if all(check["ok"] for check in checks) else "fail", "checks": checks}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
