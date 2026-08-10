"""Starter tests for <name>'s report generator.

The end-to-end run (markdown → HTML/PDF/slides/xlsx for each locale) is
covered by the CI job which actually invokes generate_report.py and
asserts the shape of the output directory. These unit tests cover the
pure helpers — font mapping, brand/locale loading, content rendering —
so regressions are caught before paying the 3s cost of a full render.
"""

from __future__ import annotations

from generate_report import _latex_font


def test_latex_font_returns_fallback_for_empty_stack() -> None:
    assert _latex_font("", "DejaVu Sans") == "DejaVu Sans"


def test_latex_font_maps_css_generic_to_bundled_font() -> None:
    # The brand template uses "sans-serif" which is a CSS generic family
    # and not a real font xelatex can load. Must fall back.
    result = _latex_font("sans-serif", "DejaVu Sans")
    assert result == "DejaVu Sans"


def test_latex_font_extracts_first_name_from_stack() -> None:
    # Real world config: Inter, system-ui, -apple-system, sans-serif
    # Inter isn't bundled in the Docker image, so we expect the mapper
    # to rewrite it to a bundled equivalent.
    result = _latex_font("Inter, system-ui, -apple-system, sans-serif", "DejaVu Sans")
    assert result == "DejaVu Sans"


def test_latex_font_preserves_uncommon_real_fonts() -> None:
    # If the operator installs a specific font in the image, the mapper
    # should leave it alone (they know what they're doing).
    result = _latex_font("UnusualFont", "DejaVu Sans")
    assert result == "UnusualFont"


def test_latex_font_maps_serif_web_fonts_to_dejavu_serif() -> None:
    for web_serif in ("georgia", "Georgia", "Times New Roman", "palatino"):
        assert _latex_font(web_serif, "DejaVu Sans") == "DejaVu Serif"


def test_latex_font_maps_mono_web_fonts_to_dejavu_mono() -> None:
    for web_mono in ("Menlo", "Monaco", "Consolas", "Fira Code"):
        assert _latex_font(web_mono, "DejaVu Sans") == "DejaVu Sans Mono"


def test_latex_font_strips_quoted_first_entry() -> None:
    # CSS quotes are common for font names with spaces
    assert _latex_font('"Open Sans", sans-serif', "DejaVu Sans") == "DejaVu Sans"
