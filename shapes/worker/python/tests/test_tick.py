"""Smoke tests for <name>'s worker loop.

These are the starter tests every worker-shape project ships with. They
exercise the pieces you can unit-test without a full loop: pull_batch,
process_item, touch_heartbeat. The real loop is covered by the CI
integration stage (`make test` runs the container and waits for the
heartbeat file to appear).
"""

from __future__ import annotations

from pathlib import Path

import worker


def test_pull_batch_returns_a_list() -> None:
    batch = worker.pull_batch()
    assert isinstance(batch, list), "pull_batch must return a list"


def test_process_item_is_idempotent_on_success() -> None:
    # The stub always returns True, but the contract (AGENTS.md §12) is
    # that callers can retry with the same item. This test enforces that
    # idempotency check stays in place if someone rewires process_item.
    result_a = worker.process_item({"id": 1})
    result_b = worker.process_item({"id": 1})
    assert result_a == result_b


def test_touch_heartbeat_creates_the_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(worker, "DATA_DIR", tmp_path)
    monkeypatch.setattr(worker, "HEARTBEAT", tmp_path / "heartbeat")
    worker.touch_heartbeat()
    assert (tmp_path / "heartbeat").exists(), "heartbeat file must be created"


def test_heartbeat_refreshes_mtime_on_repeat_touch(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import time as _time

    monkeypatch.setattr(worker, "DATA_DIR", tmp_path)
    monkeypatch.setattr(worker, "HEARTBEAT", tmp_path / "heartbeat")
    worker.touch_heartbeat()
    first = (tmp_path / "heartbeat").stat().st_mtime
    _time.sleep(0.05)
    worker.touch_heartbeat()
    second = (tmp_path / "heartbeat").stat().st_mtime
    assert second >= first, "second touch must not go backwards in time"
