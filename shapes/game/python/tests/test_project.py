"""Tests for <name>'s project layout and engine wiring.

The gameplay checks live in `scripts/qa_check.gd`, which runs inside Godot and
can use the real scene loader and the real simulation. These are the fast,
engine-free checks that catch a broken project before the engine is even
started — worth having separate, because they take milliseconds and the
engine takes seconds.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import qa_check  # noqa: E402


class TestProjectFile:
    def test_project_godot_exists(self):
        assert (PROJECT_ROOT / "project.godot").is_file()

    def test_declares_a_main_scene(self):
        # project.godot is INI-*like*, not INI: `config_version` sits before
        # any section header, which configparser rejects outright. Match the
        # key directly rather than pretending the format is something it isn't.
        text = (PROJECT_ROOT / "project.godot").read_text(encoding="utf-8")
        match = re.search(r'run/main_scene\s*=\s*"([^"]+)"', text)
        assert match, "no main scene declared — the game has no entry point"
        main_scene = match.group(1)
        assert (PROJECT_ROOT / main_scene.removeprefix("res://")).is_file(), f"main scene {main_scene} does not exist"

    def test_physics_tick_is_fixed(self):
        # A variable timestep makes the simulation non-reproducible, which
        # breaks replays, netcode rollback and save compatibility.
        text = (PROJECT_ROOT / "project.godot").read_text(encoding="utf-8")
        assert "physics_ticks_per_second" in text


class TestSceneReferences:
    def scenes(self) -> list[Path]:
        return list(PROJECT_ROOT.rglob("*.tscn"))

    def test_there_is_at_least_one_scene(self):
        assert self.scenes()

    def test_every_res_reference_exists(self):
        # The same check qa_check.gd performs inside the engine, done here so
        # a dangling reference fails in milliseconds rather than after a
        # container build.
        pattern = re.compile(r'path="(res://[^"]+)"')
        missing = []
        for scene in self.scenes():
            for ref in pattern.findall(scene.read_text(encoding="utf-8")):
                if not (PROJECT_ROOT / ref.removeprefix("res://")).exists():
                    missing.append(f"{scene.name} -> {ref}")
        assert not missing, f"dangling references: {missing}"


class TestScripts:
    def test_gdscript_files_exist(self):
        assert list(PROJECT_ROOT.rglob("*.gd"))

    def test_scripts_avoid_global_class_names_for_dependencies(self):
        # Global `class_name` resolution needs Godot's script cache, which a
        # fresh clone does not have. Depending on it makes the first CI run
        # fail for a reason that looks nothing like the cause.
        for script in (PROJECT_ROOT / "scripts").glob("*.gd"):
            text = script.read_text(encoding="utf-8")
            if "Sim.new(" in text:
                assert "preload(" in text, f"{script.name} uses the global class name without a preload"


class TestGodotDiscovery:
    def test_finds_an_explicit_path(self, tmp_path: Path) -> None:
        fake = tmp_path / "godot"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        assert qa_check.find_godot(str(fake)) is not None

    def test_returns_none_when_absent(self, monkeypatch):
        monkeypatch.setattr(qa_check, "CANDIDATES", ())
        monkeypatch.delenv("GODOT_BIN", raising=False)
        assert qa_check.find_godot(None) is None
