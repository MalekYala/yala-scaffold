"""Workflow runner for <name>.

Shape: browser (multi-step browser automation).

Workflows are **data**, not code: a list of steps in `workflows/*.json`. That
keeps the interesting decisions — what to click, what to wait for, what to
assert — in one reviewable place, and lets `qa_check.py` inspect a workflow
without executing it. Adding a step never means editing this file.

The two rules this runner enforces, because they are what separates automation
that works from automation that works on your laptop:

**Wait for conditions, never for time.** There is no `sleep` step and there
never should be. A fixed delay is a bet that the machine running it is at least
as fast as yours, and CI loses that bet constantly. Every step here waits for a
state the page can actually be in.

**Every workflow must assert something.** A run where every selector matched
nothing and no assertion fired will otherwise report success — the vacuous pass
this kit refuses everywhere else. `assert_*` steps are what make a run mean
anything, and `qa_check.py` fails a workflow that has none.

On failure, a screenshot, the page HTML and a trace are written to
`artifacts/`. Browser failures in CI are usually unreproducible locally, and
without artifacts the only debugging tool left is guessing.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

PROJECT_ROOT = Path(__file__).resolve().parent
log = logging.getLogger("<name>")

# Steps that constitute an assertion. A workflow without at least one of these
# proves nothing, however many pages it visited.
ASSERTION_STEPS = {"assert_text", "assert_visible", "assert_count", "assert_url"}


@dataclass
class StepResult:
    index: int
    action: str
    ok: bool
    detail: str = ""
    duration_ms: int = 0


@dataclass
class RunResult:
    workflow: str
    steps: list[StepResult] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(step.ok for step in self.steps)

    @property
    def assertions(self) -> int:
        return sum(1 for step in self.steps if step.action in ASSERTION_STEPS)


def load_workflow(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


class WorkflowRunner:
    """Executes declarative steps against a page."""

    def __init__(self, page: Page, base_url: str, timeout_ms: int = 10000) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.timeout_ms = timeout_ms

    def run_step(self, step: dict[str, Any]) -> StepResult:
        action = step.get("action", "")
        started = time.perf_counter()
        try:
            detail = self._dispatch(action, step)
            ok = True
        except (PlaywrightTimeout, PlaywrightError, AssertionError) as exc:
            detail = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
            ok = False
        elapsed = int((time.perf_counter() - started) * 1000)
        return StepResult(index=step.get("_index", 0), action=action, ok=ok, detail=detail, duration_ms=elapsed)

    def _dispatch(self, action: str, step: dict[str, Any]) -> str:
        selector: str = step.get("selector", "")
        timeout = int(step.get("timeout_ms", self.timeout_ms))

        if action == "goto":
            url = step["url"]
            full = url if url.startswith("http") else f"{self.base_url}{url}"
            # `domcontentloaded` rather than `load`: waiting for every image and
            # font makes runs slow and flaky for no benefit, since the next step
            # waits for what it actually needs anyway.
            self.page.goto(full, wait_until="domcontentloaded", timeout=timeout)
            return full

        if action == "fill":
            self.page.fill(selector, step["value"], timeout=timeout)
            return f"{selector} = {step['value']!r}"

        if action == "click":
            self.page.click(selector, timeout=timeout)
            return selector

        if action == "wait_for":
            # The only kind of waiting this runner offers: a condition, with a
            # bound. There is deliberately no sleep step.
            self.page.wait_for_selector(selector, timeout=timeout, state=step.get("state", "visible"))
            return f"{selector} ({step.get('state', 'visible')})"

        if action == "assert_visible":
            self.page.wait_for_selector(selector, timeout=timeout, state="visible")
            return f"{selector} is visible"

        if action == "assert_text":
            self.page.wait_for_selector(selector, timeout=timeout)
            actual = self.page.inner_text(selector).strip()
            expected = step["expect"]
            if step.get("exact", False):
                assert actual == expected, f"{selector}: {actual!r} != {expected!r}"
            else:
                assert expected.lower() in actual.lower(), f"{selector}: {actual[:80]!r} does not contain {expected!r}"
            return f"{selector} contains {expected!r}"

        if action == "assert_count":
            self.page.wait_for_selector(selector, timeout=timeout)
            # Distinct names from the assert_text branch above: reusing `actual`
            # and `expected` for a count made them str-then-int in one scope.
            found = len(self.page.query_selector_all(selector))
            wanted = int(step["expect"])
            assert found == wanted, f"{selector}: found {found}, expected {wanted}"
            return f"{selector} x{found}"

        if action == "assert_url":
            expected = step["expect"]
            assert expected in self.page.url, f"url {self.page.url!r} lacks {expected!r}"
            return self.page.url

        if action == "screenshot":
            name = step.get("name", "step")
            path = PROJECT_ROOT / "artifacts" / f"{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(path))
            return str(path.name)

        # An unknown action must stop the run. Skipping it would let a typo in
        # a workflow silently remove a step — including an assertion.
        raise AssertionError(f"unknown action {action!r}")


def run_workflow(
    workflow_path: Path,
    base_url: str,
    headless: bool = True,
    trace: bool = False,
) -> RunResult:
    """Execute one workflow file end to end."""
    workflow = load_workflow(workflow_path)
    result = RunResult(workflow=workflow.get("name", workflow_path.stem))
    artifacts_dir = PROJECT_ROOT / "artifacts"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        if trace:
            context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        runner = WorkflowRunner(page, base_url, int(workflow.get("timeout_ms", 10000)))

        try:
            for index, step in enumerate(workflow.get("steps", []), 1):
                step["_index"] = index
                step_result = runner.run_step(step)
                result.steps.append(step_result)
                log.info(f"[<name>-perf] phase=step duration_ms={step_result.duration_ms} action={step_result.action} ok={step_result.ok}")
                if not step_result.ok:
                    # Capture everything needed to debug a failure that will
                    # not reproduce locally. Doing this only on failure keeps
                    # successful runs fast and the artifacts directory small.
                    artifacts_dir.mkdir(parents=True, exist_ok=True)
                    stem = f"{result.workflow}-step{index}-failed"
                    try:
                        page.screenshot(path=str(artifacts_dir / f"{stem}.png"))
                        (artifacts_dir / f"{stem}.html").write_text(page.content(), encoding="utf-8")
                        result.artifacts += [f"{stem}.png", f"{stem}.html"]
                    except PlaywrightError:
                        pass
                    break
        finally:
            if trace:
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                trace_path = artifacts_dir / f"{result.workflow}-trace.zip"
                context.tracing.stop(path=str(trace_path))
                result.artifacts.append(trace_path.name)
            context.close()
            browser.close()

    return result
