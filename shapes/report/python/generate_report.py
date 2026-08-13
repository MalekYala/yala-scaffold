"""Document generator for <name>.

Shape: report — reads content + templates + brand + locales, renders one or
more branded documents per language, writes them to outputs/, exits.

Required outputs (per language code in locales/):
    outputs/report_<lang>.pdf    — branded PDF
    outputs/report_<lang>.html   — branded standalone HTML
    outputs/slides_<lang>.html   — branded reveal.js slideshow
    outputs/summary_<lang>.xlsx  — branded Excel summary
    outputs/manifest.json        — success sentinel (written last)

How branding works:
    brand/config.json        is loaded and passed to Jinja2 templates
                             (brand.colors.primary, brand.display_name, etc.)
    brand/logo.svg           is referenced from the Pandoc header for the PDF
    brand/config.json colors are injected into a WeasyPrint CSS template
                             for consistent styling

How i18n works:
    locales/<lang>.json      is loaded and passed to Jinja2 as `t`
    content/report.md        is a Jinja2 template — reference {{ t.app.title }}
    One pass per language    (en, es, de, ...) produces per-locale artifacts

CONVERTX_URL, if set, offloads specific conversions to an operator's
ConvertX instance (see README.md / docs/SETUP.md).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "info").upper()
OUTPUTS_DIR: Path = Path(os.environ.get("OUTPUTS_DIR", "outputs"))
CONTENT_DIR: Path = Path(os.environ.get("CONTENT_DIR", "content"))
TEMPLATES_DIR: Path = Path(os.environ.get("TEMPLATES_DIR", "templates"))
BRAND_CONFIG_PATH: Path = Path(os.environ.get("BRAND_CONFIG_PATH", "brand/config.json"))
LOCALES_DIR: Path = Path(os.environ.get("LOCALES_DIR", "locales"))
CONVERTX_URL: str = os.environ.get("CONVERTX_URL", "").rstrip("/")
# Comma-separated list of languages to build, or "all" to use every locale file
BUILD_LANGS: str = os.environ.get("BUILD_LANGS", "all")

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>")


def load_brand() -> dict[str, Any]:
    """Load brand/config.json, return as a dict. Falls back to a minimal
    default if the file is missing so the build doesn't crash on bare repos.
    """
    if not BRAND_CONFIG_PATH.exists():
        log.warning(f"brand config not found at {BRAND_CONFIG_PATH} — using defaults")
        return {
            "name": "<name>",
            "display_name": "<name>",
            "tagline": "",
            "description": "",
            "colors": {
                "primary": "#1f77b4",
                "secondary": "#ff7f0e",
                "accent": "#2ca02c",
                "text": "#111111",
                "text_muted": "#6b7280",
                "background": "#ffffff",
                "border": "#d0d7de",
            },
            "fonts": {"heading": "sans-serif", "body": "sans-serif", "mono": "monospace"},
            "logo": {},
            "contact": {},
            "legal": {
                "company_name": "The Project Authors",
                "copyright_year": str(time.gmtime().tm_year),
            },
        }
    result: dict[str, Any] = json.loads(BRAND_CONFIG_PATH.read_text())
    return result


def discover_locales() -> list[str]:
    """Return the list of language codes with a locales/<lang>.json file."""
    if not LOCALES_DIR.exists():
        log.warning(f"locales dir not found at {LOCALES_DIR} — defaulting to en")
        return ["en"]
    codes = sorted(p.stem for p in LOCALES_DIR.glob("*.json") if p.stem not in ("schema", "README"))
    if not codes:
        log.warning("no locale files found — defaulting to en")
        return ["en"]
    if BUILD_LANGS != "all":
        requested = {s.strip() for s in BUILD_LANGS.split(",") if s.strip()}
        codes = [c for c in codes if c in requested]
    return codes


def load_locale(lang: str) -> dict[str, Any]:
    """Load locales/<lang>.json. Missing top-level namespaces fall back to en.json."""
    en_path = LOCALES_DIR / "en.json"
    base: dict[str, Any] = json.loads(en_path.read_text()) if en_path.exists() else {}
    if lang == "en":
        return base
    lang_path = LOCALES_DIR / f"{lang}.json"
    if not lang_path.exists():
        return base
    translated: dict[str, Any] = json.loads(lang_path.read_text())
    # Shallow merge at the namespace level — en's `errors` dict keeps all keys
    # even if the target language only translated a few. Good enough for our
    # namespaces; use jinja defaults for deeper fallbacks.
    merged: dict[str, Any] = dict(base)
    for k, v in translated.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merged[k] = {**base[k], **v}
        else:
            merged[k] = v
    return merged


def render_content(lang: str, brand: dict[str, Any], locale: dict[str, Any]) -> str:
    """Render content/report.md as a Jinja2 template with brand + locale
    variables available.
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(CONTENT_DIR)),
        autoescape=select_autoescape(disabled_extensions=("md",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.md")
    return template.render(
        brand=brand,
        t=locale,
        lang=lang,
        now=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    )


def write_brand_css() -> Path:
    """Write a small CSS file derived from brand colors/fonts that Pandoc
    and WeasyPrint include for consistent styling.
    """
    brand = load_brand()
    colors = brand.get("colors", {})
    fonts = brand.get("fonts", {})
    css_path = OUTPUTS_DIR / "_brand.css"
    css = f"""
/* Auto-generated from brand/config.json — do not edit by hand */
:root {{
  --brand-primary: {colors.get("primary", "#1f77b4")};
  --brand-secondary: {colors.get("secondary", "#ff7f0e")};
  --brand-text: {colors.get("text", "#111111")};
  --brand-muted: {colors.get("text_muted", "#6b7280")};
  --brand-background: {colors.get("background", "#ffffff")};
  --brand-border: {colors.get("border", "#d0d7de")};
}}
body {{
  font-family: {fonts.get("body", "system-ui, sans-serif")};
  color: var(--brand-text);
  background: var(--brand-background);
  line-height: 1.5;
  max-width: 780px;
  margin: 2em auto;
  padding: 0 1em;
}}
h1, h2, h3, h4, h5, h6 {{
  font-family: {fonts.get("heading", "system-ui, sans-serif")};
  color: var(--brand-primary);
}}
h1 {{ border-bottom: 2px solid var(--brand-primary); padding-bottom: 0.3em; }}
a {{ color: var(--brand-primary); }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid var(--brand-border); padding: 0.5em 0.8em; text-align: left; }}
th {{ background: var(--brand-primary); color: #ffffff; }}
"""
    css_path.write_text(css)
    return css_path


_LATEX_SAFE_FONTS = {
    "serif": "DejaVu Serif",
    "sans-serif": "DejaVu Sans",
    "monospace": "DejaVu Sans Mono",
    "system-ui": "DejaVu Sans",
    "ui-serif": "DejaVu Serif",
    "ui-sans-serif": "DejaVu Sans",
    "ui-monospace": "DejaVu Sans Mono",
}


def _latex_font(css_stack: str, fallback: str) -> str:
    """brand/config.json stores fonts as CSS stacks (e.g. "Inter, system-ui,
    -apple-system, sans-serif") which are invalid xelatex mainfont values.
    Extract the first plausible font name, strip quotes, and if it's a CSS
    generic family map it to a bundled DejaVu equivalent.
    """
    if not css_stack:
        return fallback
    # First comma-separated entry
    first = css_stack.split(",")[0].strip()
    # Strip surrounding single/double quotes
    first = first.strip("\"'")
    # Reject empty / generic / system-specific
    if not first or first.startswith("-"):
        return fallback
    low = first.lower()
    if low in _LATEX_SAFE_FONTS:
        return _LATEX_SAFE_FONTS[low]
    # Specific fonts (e.g. "Inter", "Roboto") — only usable if the Docker
    # image has them installed. The shipped image bundles DejaVu + Liberation
    # only, so map common web fonts back to safe fallbacks.
    if low in {
        "inter",
        "roboto",
        "open sans",
        "lato",
        "source sans pro",
        "segoe ui",
        "helvetica",
        "arial",
    }:
        return "DejaVu Sans"
    if low in {"menlo", "monaco", "courier new", "consolas", "source code pro", "fira code"}:
        return "DejaVu Sans Mono"
    if low in {"georgia", "palatino", "times new roman", "times"}:
        return "DejaVu Serif"
    return first  # assume it's a real installed font


def render_pdf(lang: str, rendered_md: Path, out_path: Path, brand: dict[str, Any]) -> None:
    """Render a markdown file to PDF via pandoc + xelatex, with brand values
    injected as LaTeX variables. Fonts from brand/config.json are CSS stacks;
    we extract the first name and map to LaTeX-installed equivalents.
    """
    _t = time.monotonic()
    colors = brand.get("colors", {})
    fonts = brand.get("fonts", {})
    main_font = _latex_font(fonts.get("body", ""), "DejaVu Serif")
    mono_font = _latex_font(fonts.get("mono", ""), "DejaVu Sans Mono")
    # NOTE: title/subtitle/author/date/lang come from the YAML frontmatter
    # in the rendered markdown (content/report.md is a Jinja2 template that
    # fills them from brand/config.json). Passing them as `-V` flags too
    # causes pandoc to set them twice and triggers hyperref expansion bugs.
    #
    # Brand hex colors need to be passed via a LaTeX header-include because
    # `#` is a LaTeX macro parameter character and pandoc's `-V linkcolor=`
    # only accepts xcolor-named colors, not raw hex. We write a tiny
    # preamble file that defines `brandprimary` as the hex value and uses
    # it for link/url color.
    primary_hex = colors.get("primary", "#1f77b4").lstrip("#")
    # Only define the color in the header-include — pandoc's own template
    # handles the \hypersetup call, and our color name becomes the value
    # it uses via the -V linkcolor flags below.
    header_tex = OUTPUTS_DIR / f"_brand_preamble_{lang}.tex"
    header_tex.write_text(f"\\usepackage{{xcolor}}\n\\definecolor{{brandprimary}}{{HTML}}{{{primary_hex}}}\n")
    cmd = [
        "pandoc",
        str(rendered_md),
        "-o",
        str(out_path),
        "--pdf-engine=xelatex",
        "-V",
        "geometry:margin=1in",
        "-V",
        f"mainfont={main_font}",
        "-V",
        f"monofont={mono_font}",
        "-V",
        "linkcolor=brandprimary",
        "-V",
        "urlcolor=brandprimary",
        "-V",
        "colorlinks=true",
        "-H",
        str(header_tex),
    ]
    subprocess.run(cmd, check=True)
    log.info(f"[<name>-perf] phase=pandoc_pdf lang={lang} duration_ms={int((time.monotonic() - _t) * 1000)} out={out_path}")


def render_html(lang: str, rendered_md: Path, out_path: Path, css_path: Path) -> None:
    _t = time.monotonic()
    subprocess.run(
        [
            "pandoc",
            str(rendered_md),
            "-o",
            str(out_path),
            "--standalone",
            "--self-contained",
            "--css",
            str(css_path),
            "-V",
            f"lang={lang}",
        ],
        check=True,
    )
    log.info(f"[<name>-perf] phase=pandoc_html lang={lang} duration_ms={int((time.monotonic() - _t) * 1000)}")


def render_slides(lang: str, rendered_md: Path, out_path: Path, css_path: Path) -> None:
    _t = time.monotonic()
    subprocess.run(
        [
            "pandoc",
            str(rendered_md),
            "-o",
            str(out_path),
            "-t",
            "revealjs",
            "--standalone",
            "--css",
            str(css_path),
            "-V",
            "theme=white",
            "-V",
            f"lang={lang}",
        ],
        check=True,
    )
    log.info(f"[<name>-perf] phase=pandoc_slides lang={lang} duration_ms={int((time.monotonic() - _t) * 1000)}")


def render_excel(lang: str, brand: dict[str, Any], locale: dict[str, Any], out_path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    _t = time.monotonic()
    wb = Workbook()
    ws = wb.active
    ws.title = locale.get("nav", {}).get("home", "Summary")[:31]  # xlsx sheet name limit

    primary_hex = brand.get("colors", {}).get("primary", "#1f77b4").lstrip("#")
    header_fill = PatternFill(start_color=primary_hex, end_color=primary_hex, fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    title = locale.get("app", {}).get("title", brand.get("display_name", "<name>"))
    tagline = locale.get("app", {}).get("tagline", brand.get("tagline", ""))

    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=16, color=primary_hex)
    ws.merge_cells("A1:B1")
    ws["A2"] = tagline
    ws.merge_cells("A2:B2")

    ws["A4"] = "Key"
    ws["B4"] = "Value"
    for col in ("A4", "B4"):
        ws[col].fill = header_fill
        ws[col].font = header_font
        ws[col].alignment = Alignment(horizontal="left")

    row = 5
    for k, v in (brand.get("contact") or {}).items():
        if not v:
            continue
        ws[f"A{row}"] = k
        ws[f"B{row}"] = str(v)
        row += 1

    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 40

    wb.save(out_path)
    log.info(f"[<name>-perf] phase=xlsx lang={lang} duration_ms={int((time.monotonic() - _t) * 1000)}")


def main() -> None:
    _t_total = time.monotonic()
    log.info("<name> report generation starting")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    source_md = CONTENT_DIR / "report.md"
    if not source_md.exists():
        log.error(f"no content at {source_md}")
        sys.exit(1)

    brand = load_brand()
    locales = discover_locales()
    log.info(f"brand: {brand.get('display_name')} — generating for locales: {locales}")

    css_path = write_brand_css()
    generated: list[str] = []

    for lang in locales:
        locale = load_locale(lang)
        log.info(f"rendering locale={lang}")

        # 1. Render content Markdown with Jinja2 (brand + locale vars)
        rendered_md_path = OUTPUTS_DIR / f"_rendered_{lang}.md"
        rendered_md_path.write_text(render_content(lang, brand, locale))

        # 2. PDF
        pdf_path = OUTPUTS_DIR / f"report_{lang}.pdf"
        try:
            render_pdf(lang, rendered_md_path, pdf_path, brand)
            generated.append(pdf_path.name)
        except subprocess.CalledProcessError as exc:
            log.error(f"pandoc PDF failed for {lang}: {exc}")
            sys.exit(1)

        # 3. Standalone HTML
        html_path = OUTPUTS_DIR / f"report_{lang}.html"
        render_html(lang, rendered_md_path, html_path, css_path)
        generated.append(html_path.name)

        # 4. Reveal.js slideshow
        slides_path = OUTPUTS_DIR / f"slides_{lang}.html"
        render_slides(lang, rendered_md_path, slides_path, css_path)
        generated.append(slides_path.name)

        # 5. Excel summary (branded)
        xlsx_path = OUTPUTS_DIR / f"summary_{lang}.xlsx"
        render_excel(lang, brand, locale, xlsx_path)
        generated.append(xlsx_path.name)

    # Success sentinel
    (OUTPUTS_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "success": True,
                "timestamp": int(time.time()),
                "brand": {
                    "name": brand.get("name"),
                    "display_name": brand.get("display_name"),
                    "primary_color": brand.get("colors", {}).get("primary"),
                },
                "locales": locales,
                "files": sorted(generated),
            },
            indent=2,
        )
    )

    log.info(f"[<name>-perf] phase=total duration_ms={int((time.monotonic() - _t_total) * 1000)} status=ok locales={len(locales)} files={len(generated)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.exception(f"report generation failed: {exc}")
        sys.exit(1)
    sys.exit(0)
