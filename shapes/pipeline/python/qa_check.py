"""E2E check for <name> (shape: pipeline).

Verifies the most recent pipeline run succeeded end-to-end and the final
output has a non-zero row count.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


class Checker:
    name = "<name>"

    def run(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        results: dict[str, Any] = {"checks": checks, "status": "ok"}

        manifest = Path("outputs/manifest.json")
        if not manifest.exists():
            checks.append(
                {
                    "name": "manifest_exists",
                    "ok": False,
                    "error": "outputs/manifest.json missing — pipeline never completed",
                }
            )
            results["status"] = "fail"
            return results

        try:
            data = json.loads(manifest.read_text())
        except Exception as exc:
            checks.append({"name": "manifest_valid", "ok": False, "error": str(exc)})
            results["status"] = "fail"
            return results

        checks.append(
            {
                "name": "manifest_success",
                "ok": bool(data.get("success")),
                "stages_run": data.get("stages_run", []),
            }
        )
        if not data.get("success"):
            results["status"] = "fail"

        # Final output row count > 0
        final = data.get("final_output", {})
        rows = final.get("row_count", 0)
        checks.append(
            {
                "name": "final_row_count",
                "ok": rows > 0,
                "row_count": rows,
            }
        )
        if rows <= 0:
            results["status"] = "fail"

        # The file referenced by the final output exists
        final_path = final.get("output")
        if final_path:
            exists = Path(final_path).exists()
            checks.append(
                {
                    "name": "final_file_exists",
                    "ok": exists,
                    "path": final_path,
                }
            )
            if not exists:
                results["status"] = "fail"

        return results


CHECKER_CLASS = Checker


if __name__ == "__main__":
    result = Checker().run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
