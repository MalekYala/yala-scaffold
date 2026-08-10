"""Tests for <name>'s workflow definitions and runner.

The fast, static half: workflow shape, assertion presence, no time-based
waits. The slow half — actually driving Chromium — lives in qa_check.py, which
runs every workflow against the committed fixture site.

Splitting them that way keeps `make test` quick enough to run constantly while
still having something that proves the browser path works.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fixtures.server import FixtureSite  # noqa: E402
from runner import ASSERTION_STEPS, load_workflow  # noqa: E402

WORKFLOWS = sorted((PROJECT_ROOT / "workflows").glob("*.json"))
KNOWN_ACTIONS = ASSERTION_STEPS | {"goto", "fill", "click", "wait_for", "screenshot"}


class TestWorkflowDefinitions:
    def test_there_is_at_least_one_workflow(self) -> None:
        assert WORKFLOWS, "a browser project with no workflows automates nothing"

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.stem)
    def test_is_valid_json_with_steps(self, path: Path) -> None:
        workflow = load_workflow(path)
        assert workflow.get("steps"), f"{path.stem} has no steps"

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.stem)
    def test_asserts_something(self, path: Path) -> None:
        # A workflow can visit every page, match nothing, and report success.
        # At least one assertion is what makes a green run mean anything.
        actions = {step.get("action") for step in load_workflow(path)["steps"]}
        assert actions & ASSERTION_STEPS, f"{path.stem} makes no assertion"

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.stem)
    def test_uses_only_known_actions(self, path: Path) -> None:
        # An unrecognised action is usually a typo, and a typo that silently
        # skipped a step could silently remove an assertion.
        for step in load_workflow(path)["steps"]:
            assert step.get("action") in KNOWN_ACTIONS, f"{path.stem}: {step.get('action')!r}"

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.stem)
    def test_never_waits_on_a_fixed_delay(self, path: Path) -> None:
        # The single largest source of browser flake: a sleep is a bet that CI
        # is at least as fast as your laptop.
        actions = {step.get("action") for step in load_workflow(path)["steps"]}
        assert not (actions & {"sleep", "wait", "delay", "pause"}), f"{path.stem} sleeps"

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.stem)
    def test_steps_that_need_a_selector_have_one(self, path: Path) -> None:
        needs_selector = KNOWN_ACTIONS - {"goto", "screenshot", "assert_url"}
        for index, step in enumerate(load_workflow(path)["steps"], 1):
            if step.get("action") in needs_selector:
                assert step.get("selector"), f"{path.stem} step {index} has no selector"


class TestFixtureServer:
    def test_binds_an_ephemeral_port(self) -> None:
        # A hardcoded port on a machine running many services is a coin flip,
        # and losing it produces a test that fails against somebody else's
        # service — which reads as a broken selector.
        with FixtureSite() as site:
            assert site.port > 0
            assert site.base_url.startswith("http://127.0.0.1:")

    def test_two_servers_do_not_collide(self) -> None:
        with FixtureSite() as a, FixtureSite() as b:
            assert a.port != b.port

    def test_serves_the_committed_site(self) -> None:
        import urllib.request

        with FixtureSite() as site:
            with urllib.request.urlopen(f"{site.base_url}/", timeout=10) as response:
                body = response.read().decode()
            assert response.status == 200
            assert "Fixture site" in body

    def test_stops_cleanly(self) -> None:
        import socket

        site = FixtureSite()
        site.start()
        port = site.port
        site.stop()
        # The port must be released, or repeated runs leak listeners.
        with socket.socket() as probe:
            probe.settimeout(2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
