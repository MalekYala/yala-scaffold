from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from app import app


def sample_png(width: int = 16, height: int = 12) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 200)).save(output, format="PNG")
    return output.getvalue()


def test_interface_loads() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Image-to-image interface" in response.text


def test_transform_returns_valid_png() -> None:
    response = TestClient(app).post(
        "/api/transform",
        files={"file": ("source.png", sample_png(), "image/png")},
        data={"effect": "invert", "strength": "1"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(response.content)) as result:
        assert result.format == "PNG"
        assert result.size == (16, 12)
        assert result.getpixel((0, 0)) == (215, 135, 55)


def test_invalid_upload_is_rejected() -> None:
    response = TestClient(app).post(
        "/api/transform",
        files={"file": ("source.txt", b"not an image", "text/plain")},
        data={"effect": "enhance", "strength": "0.5"},
    )
    assert response.status_code == 415


def test_unknown_effect_is_rejected() -> None:
    response = TestClient(app).post(
        "/api/transform",
        files={"file": ("source.png", sample_png(), "image/png")},
        data={"effect": "unknown", "strength": "0.5"},
    )
    assert response.status_code == 422
