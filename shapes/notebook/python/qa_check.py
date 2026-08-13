"""E2E check for <name> (shape: notebook).

Executes every .ipynb under notebooks/ via nbclient. Each notebook must run
cleanly from a fresh kernel with no errors.

Run:
    python3 qa_check.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


class Checker:
    name = "<name>"

    def run(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        results: dict[str, Any] = {"checks": checks, "status": "ok"}
        notebooks_dir = Path(os.environ.get("NOTEBOOKS_DIR", "notebooks"))

        if not notebooks_dir.exists():
            checks.append(
                {
                    "name": "notebooks_dir",
                    "ok": False,
                    "error": f"{notebooks_dir} not found",
                }
            )
            results["status"] = "fail"
            return results

        notebooks = sorted(notebooks_dir.rglob("*.ipynb"))
        if not notebooks:
            checks.append(
                {
                    "name": "notebooks_present",
                    "ok": False,
                    "error": f"no .ipynb files in {notebooks_dir}",
                }
            )
            results["status"] = "fail"
            return results

        try:
            import nbformat
            from nbclient import NotebookClient
        except ImportError as exc:
            checks.append(
                {
                    "name": "imports",
                    "ok": False,
                    "error": f"{exc} — add nbclient/nbformat to requirements.txt",
                }
            )
            results["status"] = "fail"
            return results

        for nb_path in notebooks:
            _t = time.monotonic()
            try:
                nb = nbformat.read(nb_path, as_version=4)  # type: ignore[no-untyped-call]
                client = NotebookClient(nb, timeout=120, kernel_name="python3")
                client.execute()
                elapsed = int((time.monotonic() - _t) * 1000)
                cells = sum(1 for c in nb.cells if c.cell_type == "code")
                checks.append(
                    {
                        "name": f"notebook_{nb_path.name}",
                        "ok": True,
                        "cells_executed": cells,
                        "duration_ms": elapsed,
                    }
                )
            except Exception as exc:
                elapsed = int((time.monotonic() - _t) * 1000)
                checks.append(
                    {
                        "name": f"notebook_{nb_path.name}",
                        "ok": False,
                        "error": str(exc)[:200],
                        "duration_ms": elapsed,
                    }
                )
                results["status"] = "fail"

        return results


CHECKER_CLASS = Checker


if __name__ == "__main__":
    result = Checker().run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
