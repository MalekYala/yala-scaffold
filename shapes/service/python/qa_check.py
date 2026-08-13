"""End-to-end health check for <name> (shape: service).

Modes:
    python3 qa_check.py            # live probe: /health + every GET route
    python3 qa_check.py --audit    # static: report discovered route coverage
    python3 qa_check.py --smoke    # full E2E: live probe + fail on empty-list
                                   # responses unless the path is in EMPTY_OK.

--smoke is what the plan-to-PR workflow invokes. It is the difference
between "/api/channels responded 200" and "/api/channels returned []" — the
latter is a silent regression and MUST fail the check.

Add a path to EMPTY_OK if an empty list is a legitimate steady state for the
endpoint (e.g. an audit log that starts blank). Everything else is treated as
a broken dependency or mis-wired startup.

Routes are discovered across the whole project, not just app.py: any service
that grows past a single file registers its routes in a module or on an
APIRouter, and a discoverer that only reads app.py then finds nothing and
passes every probe over an empty set. Vacuous success is worse than failure,
so --audit exits non-zero when it finds no routes at all.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

# Paths where an empty list response is a valid steady state. Extend per-project.
EMPTY_OK: set[str] = set()


# Directories that never contain servable routes. Scanning them wastes time and
# invites false positives from fixtures and vendored code.
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "tests",
    "test",
    "bot",
    "rag",
    "scripts",
    "outputs",
    "data",
    "memory",
    "locales",
    "brand",
}


def _routes_in_source(text: str) -> list[str]:
    """Every GET path decorated in one module.

    Matches `@app.get(...)` and `@router.get(...)` alike — the decorator is
    looked up by attribute name, not by the object it hangs off, so whatever
    the router variable is called it still counts.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    paths: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            if getattr(deco.func, "attr", None) != "get":
                continue
            if deco.args and isinstance(deco.args[0], ast.Constant):
                value = deco.args[0].value
                if isinstance(value, str):
                    paths.append(value)
    return paths


def _discover_get_routes(app_py: Path) -> list[str]:
    """Every GET route in the project, in a stable order, de-duplicated."""
    root = app_py.parent if app_py.name.endswith(".py") else app_py
    seen: dict[str, None] = {}

    candidates: list[Path] = []
    if app_py.exists():
        candidates.append(app_py)
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name == "qa_check.py" or path == app_py:
            continue
        candidates.append(path)

    for path in candidates:
        try:
            text = path.read_text()
        except OSError:
            continue
        for route in _routes_in_source(text):
            seen.setdefault(route, None)
    return list(seen)


def _is_probeable(path: str) -> bool:
    """Can this route be fetched by its literal template?

    A parameterised route ("/jobs/{job_id}") is a 404 by construction — the
    braces are not a real path. Probing it reports a permanent, meaningless
    failure that trains everyone to ignore the check.
    """
    return "{" not in path and "<" not in path


class Checker:
    name: str = "<name>"

    def __init__(self, smoke: bool = False) -> None:
        self.smoke = smoke

    def run(self) -> dict[str, Any]:
        port = os.environ.get("PORT", "<PORT>")
        host = os.environ.get("HOST", "127.0.0.1")
        base = f"http://{host}:{port}"
        checks: list[dict[str, Any]] = []
        results: dict[str, Any] = {"checks": checks, "status": "ok"}

        try:
            r = httpx.get(f"{base}/health", timeout=5)
            ok = r.status_code == 200
            checks.append({"name": "health", "ok": ok, "status_code": r.status_code})
            if not ok:
                results["status"] = "fail"
        except Exception as exc:
            checks.append({"name": "health", "ok": False, "error": str(exc)})
            results["status"] = "fail"
            return results

        app_py = Path(__file__).parent / "app.py"
        discovered = _discover_get_routes(app_py)
        probeable = [p for p in discovered if p != "/health" and _is_probeable(p)]

        # Finding no routes at all almost always means the discoverer is
        # pointed at the wrong place, not that the service has none. Report it
        # rather than returning a clean pass over an empty set.
        checks.append(
            {
                "name": "route_discovery",
                "ok": bool(discovered),
                "discovered": len(discovered),
                "probeable": len(probeable),
                "skipped_parameterised": [p for p in discovered if not _is_probeable(p)],
                **({} if discovered else {"hint": ("No @app.get/@router.get routes found. If this service registers routes another way, extend _discover_get_routes in qa_check.py.")}),
            }
        )
        if not discovered:
            results["status"] = "fail"

        for path in probeable:
            try:
                r = httpx.get(f"{base}{path}", timeout=5)
                ok = r.status_code == 200
                entry: dict[str, Any] = {
                    "name": path,
                    "ok": ok,
                    "status_code": r.status_code,
                }
                if ok and self.smoke:
                    try:
                        body = r.json()
                    except Exception:
                        body = None
                    lists = _find_empty_lists(body) if body is not None else []
                    if lists and path not in EMPTY_OK:
                        ok = False
                        entry["ok"] = False
                        entry["empty_lists"] = lists
                        entry["hint"] = f"GET {path} returned empty list(s) at {lists}. If this is correct steady state, add {path!r} to EMPTY_OK in qa_check.py."
                checks.append(entry)
                if not ok:
                    results["status"] = "fail"
            except Exception as exc:
                checks.append({"name": path, "ok": False, "error": str(exc)})
                results["status"] = "fail"
        return results


def _find_empty_lists(body: Any, prefix: str = "$") -> list[str]:
    """Return JSONPath-ish locations of every empty list in a decoded response."""
    hits: list[str] = []
    if isinstance(body, list) and not body:
        hits.append(prefix)
    elif isinstance(body, dict):
        for k, v in body.items():
            hits.extend(_find_empty_lists(v, f"{prefix}.{k}"))
    elif isinstance(body, list):
        for i, v in enumerate(body):
            hits.extend(_find_empty_lists(v, f"{prefix}[{i}]"))
    return hits


def audit_mode() -> int:
    """Static audit: list GET routes in app.py so a reviewer can see coverage."""
    app_py = Path(__file__).parent / "app.py"
    routes = _discover_get_routes(app_py)
    print(
        json.dumps(
            {
                "root": str(app_py.parent),
                "get_routes": routes,
                "probeable": [r for r in routes if _is_probeable(r)],
                "parameterised": [r for r in routes if not _is_probeable(r)],
            },
            indent=2,
        )
    )
    return 0 if routes else 1


CHECKER_CLASS = Checker


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", action="store_true", help="static route audit only")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="live probe + fail on empty-list responses (used by plan-to-PR)",
    )
    args = parser.parse_args()

    if args.audit:
        sys.exit(audit_mode())

    result = Checker(smoke=args.smoke).run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
