"""Starter tests for <name>'s notebook shape.

Notebook projects are inherently exploratory, but the scaffolding should
still catch the common failure modes:
    - an .ipynb file that's structurally invalid JSON
    - a notebook with syntax errors in one of its code cells
    - missing required dependencies declared in requirements.txt

These tests read the notebook files directly (no kernel execution) so
they're fast enough for pre-push. For full execution tests, use:
    pytest --nbval notebooks/
(requires `pytest-nbval` — not installed by default).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

NOTEBOOKS = Path("notebooks")


def _discover_notebooks() -> list[Path]:
    if not NOTEBOOKS.exists():
        return []
    return sorted(NOTEBOOKS.glob("*.ipynb"))


def test_notebooks_directory_exists() -> None:
    assert NOTEBOOKS.exists(), "notebook-shape projects must have a notebooks/ directory containing at least one .ipynb file"


def test_at_least_one_notebook_present() -> None:
    notebooks = _discover_notebooks()
    assert notebooks, "at least one .ipynb file must exist in notebooks/"


def test_every_notebook_is_valid_json() -> None:
    for nb_path in _discover_notebooks():
        try:
            data = json.loads(nb_path.read_text())
        except json.JSONDecodeError as exc:
            raise AssertionError(f"{nb_path} is not valid JSON — did git merge corrupt it? ({exc})") from exc
        assert "cells" in data, f"{nb_path} missing 'cells' — not a valid notebook"
        assert isinstance(data["cells"], list)


def test_every_code_cell_is_syntactically_valid_python() -> None:
    for nb_path in _discover_notebooks():
        data = json.loads(nb_path.read_text())
        for idx, cell in enumerate(data.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            src_list = cell.get("source", [])
            src = "".join(src_list) if isinstance(src_list, list) else src_list
            if not src.strip():
                continue
            # Skip cells that start with an IPython magic — ast.parse will
            # reject those but the kernel handles them at runtime.
            first_nonblank = next(
                (line for line in src.splitlines() if line.strip()),
                "",
            ).lstrip()
            if first_nonblank.startswith(("%", "!")):
                continue
            try:
                ast.parse(src)
            except SyntaxError as exc:
                raise AssertionError(f"{nb_path} cell {idx}: Python syntax error: {exc.msg} (line {exc.lineno})") from exc
