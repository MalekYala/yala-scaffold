"""E2E check for <name> (shape: report).

Asserts that generate_report.py produced the expected document artifacts for
every language listed in the manifest and that each is non-empty and of
plausible size. Also verifies outputs/manifest.json's success flag and brand
injection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, ClassVar


class Checker:
    name = "<name>"

    MIN_SIZES: ClassVar[dict[str, int]] = {
        "pdf": 1024,
        "html": 512,
        "xlsx": 1024,
    }

    def run(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        results: dict[str, Any] = {"checks": checks, "status": "ok"}

        manifest_path = Path("outputs/manifest.json")
        if not manifest_path.exists():
            checks.append(
                {
                    "name": "manifest_exists",
                    "ok": False,
                    "error": "outputs/manifest.json missing — generate_report.py never completed",
                }
            )
            results["status"] = "fail"
            return results

        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception as exc:
            checks.append({"name": "manifest_valid", "ok": False, "error": str(exc)})
            results["status"] = "fail"
            return results

        checks.append(
            {
                "name": "manifest_success",
                "ok": bool(manifest.get("success")),
                "locales": manifest.get("locales", []),
                "brand": manifest.get("brand", {}),
            }
        )
        if not manifest.get("success"):
            results["status"] = "fail"

        locales = manifest.get("locales") or ["en"]

        for lang in locales:
            expected = [
                (f"outputs/report_{lang}.pdf", self.MIN_SIZES["pdf"]),
                (f"outputs/report_{lang}.html", self.MIN_SIZES["html"]),
                (f"outputs/slides_{lang}.html", self.MIN_SIZES["html"]),
                (f"outputs/summary_{lang}.xlsx", self.MIN_SIZES["xlsx"]),
            ]
            for rel, min_size in expected:
                p = Path(rel)
                if not p.exists():
                    checks.append(
                        {
                            "name": f"file_{p.name}",
                            "ok": False,
                            "error": "missing",
                            "lang": lang,
                        }
                    )
                    results["status"] = "fail"
                    continue
                size = p.stat().st_size
                ok = size >= min_size
                checks.append(
                    {
                        "name": f"file_{p.name}",
                        "ok": ok,
                        "size_bytes": size,
                        "min_bytes": min_size,
                        "lang": lang,
                    }
                )
                if not ok:
                    results["status"] = "fail"

        # Brand was loaded and injected — sanity check
        brand_info = manifest.get("brand", {})
        brand_ok = bool(brand_info.get("primary_color") and brand_info.get("display_name"))
        checks.append(
            {
                "name": "brand_injected",
                "ok": brand_ok,
                "display_name": brand_info.get("display_name"),
                "primary_color": brand_info.get("primary_color"),
            }
        )
        if not brand_ok:
            results["status"] = "fail"

        return results


CHECKER_CLASS = Checker


if __name__ == "__main__":
    result = Checker().run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
