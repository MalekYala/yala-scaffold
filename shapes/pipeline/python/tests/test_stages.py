"""Starter tests for <name>'s multi-stage pipeline.

Covers stage discovery + stage module loading. The full end-to-end run
is covered by the CI job that actually invokes `pipeline.py` and asserts
the shape of outputs/manifest.json.
"""

from __future__ import annotations

from pathlib import Path

import pipeline


def test_discover_stages_returns_sorted_numeric_prefix_files(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Build a fake stages directory
    fake_stages = tmp_path / "stages"
    fake_stages.mkdir()
    (fake_stages / "02_transform.py").write_text("def run(ctx): return {}\n")
    (fake_stages / "01_extract.py").write_text("def run(ctx): return {}\n")
    (fake_stages / "03_load.py").write_text("def run(ctx): return {}\n")
    # A non-stage file that should be ignored
    (fake_stages / "helpers.py").write_text("# not a stage\n")
    # A stage without the numeric prefix — also ignored
    (fake_stages / "final.py").write_text("def run(ctx): return {}\n")

    monkeypatch.setattr(pipeline, "STAGES_DIR", fake_stages)

    discovered = pipeline.discover_stages()
    names = [p.name for p in discovered]
    assert names == ["01_extract.py", "02_transform.py", "03_load.py"], "discover_stages must return numeric-prefixed files in order"


def test_discover_stages_empty_when_no_matching_files(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    empty = tmp_path / "stages"
    empty.mkdir()
    monkeypatch.setattr(pipeline, "STAGES_DIR", empty)
    assert pipeline.discover_stages() == []


def test_load_stage_module_executes_the_file(tmp_path: Path) -> None:
    stage_file = tmp_path / "01_probe.py"
    stage_file.write_text("MARKER = 42\ndef run(ctx): return {'ok': True}\n")
    mod = pipeline.load_stage_module(stage_file)
    assert mod.MARKER == 42
    assert mod.run({}) == {"ok": True}


def test_load_stage_module_returns_a_callable_run_function(tmp_path: Path) -> None:
    stage_file = tmp_path / "02_probe.py"
    stage_file.write_text("def run(ctx): return {'stage_ran': True, 'input': ctx.get('prev')}\n")
    mod = pipeline.load_stage_module(stage_file)
    assert callable(getattr(mod, "run", None)), "every stage must expose a run(ctx) function"
    result = mod.run({"prev": {"count": 5}})
    assert result["stage_ran"] is True
    assert result["input"] == {"count": 5}
