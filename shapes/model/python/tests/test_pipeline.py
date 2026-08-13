"""Tests for <name>'s dataset pipeline and QA gate.

These test the parts that must never break silently: deterministic splitting,
leakage detection, contract validation, and the gate's refusal to pass on an
empty or missing evaluation.

Training and evaluation are not tested here — both need a GPU and a served
model. What *is* tested is everything that decides whether training is worth
starting and whether the result is shippable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import qa_check  # noqa: E402
from dataset.build import SYSTEM_PROMPT, bucket, to_chat  # noqa: E402
from preflight import contract_check  # noqa: E402


def run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / script), *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


class TestSplitting:
    def test_bucket_is_deterministic(self) -> None:
        # Rebuilding the dataset must not reshuffle examples across splits, or
        # every eval number becomes incomparable with the previous one.
        assert bucket("the export button does nothing") == bucket("the export button does nothing")

    def test_bucket_ignores_surrounding_whitespace(self) -> None:
        assert bucket(" hello ") == bucket("hello")

    def test_bucket_is_within_unit_interval(self) -> None:
        for text in ("a", "bb", "some longer example input", ""):
            assert 0.0 <= bucket(text) <= 1.0

    def test_different_inputs_land_differently(self) -> None:
        values = {bucket(f"example {i}") for i in range(50)}
        assert len(values) > 40, "hash bucketing should spread inputs out"


class TestChatConversion:
    def test_every_example_gets_the_same_system_prompt(self) -> None:
        first = to_chat({"input": "a", "output": {"label": "question"}})
        second = to_chat({"input": "b", "output": {"label": "billing"}})
        assert first is not None and second is not None
        assert first["messages"][0]["content"] == SYSTEM_PROMPT
        assert second["messages"][0]["content"] == SYSTEM_PROMPT

    def test_dict_output_is_serialised_compactly(self) -> None:
        example = to_chat({"input": "a", "output": {"label": "question", "confidence": "high"}})
        assert example is not None
        assert example["messages"][-1]["content"] == '{"label":"question","confidence":"high"}'

    def test_string_output_passes_through(self) -> None:
        example = to_chat({"input": "a", "output": "plain text"})
        assert example is not None
        assert example["messages"][-1]["content"] == "plain text"

    def test_missing_fields_are_rejected(self) -> None:
        assert to_chat({"input": "a"}) is None
        assert to_chat({"output": {"label": "question"}}) is None


class TestContract:
    contract: ClassVar[dict[str, Any]] = {
        "format": "json",
        "required_keys": ["label", "confidence"],
        "enums": {"label": ["bug", "question"], "confidence": ["high", "low"]},
    }

    def test_valid_target_passes(self) -> None:
        assert contract_check('{"label":"question","confidence":"high"}', self.contract) is None

    def test_unparseable_target_is_rejected(self) -> None:
        assert contract_check("not json", self.contract) is not None

    def test_missing_required_key_is_rejected(self) -> None:
        problem = contract_check('{"label":"question"}', self.contract)
        assert problem is not None and "confidence" in problem

    def test_value_outside_the_enum_is_rejected(self) -> None:
        problem = contract_check('{"label":"explode","confidence":"high"}', self.contract)
        assert problem is not None and "explode" in problem

    def test_no_contract_accepts_anything(self) -> None:
        assert contract_check("anything at all", {}) is None


class TestPreflightDetectsLeakage:
    def test_shared_input_between_splits_fails(self, tmp_path: Path) -> None:
        # The failure this guards against looks like success on every metric
        # you are watching, right up until production.
        shared = {
            "messages": [
                {"role": "system", "content": "S"},
                {"role": "user", "content": "the same input"},
                {"role": "assistant", "content": '{"label":"question","confidence":"high"}'},
            ]
        }
        train = tmp_path / "train.jsonl"
        val = tmp_path / "val.jsonl"
        train.write_text(json.dumps(shared) + "\n")
        val.write_text(json.dumps(shared) + "\n")

        result = run("preflight.py", "--train", str(train), "--val", str(val))
        assert result.returncode == 1
        assert "BOTH train and val" in result.stderr

    def test_disjoint_splits_pass(self, tmp_path: Path) -> None:
        def example(text: str) -> str:
            return json.dumps(
                {
                    "messages": [
                        {"role": "system", "content": "S"},
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": '{"label":"question","confidence":"high"}'},
                    ]
                }
            )

        train = tmp_path / "train.jsonl"
        val = tmp_path / "val.jsonl"
        train.write_text(example("one") + "\n")
        val.write_text(example("two") + "\n")

        result = run("preflight.py", "--train", str(train), "--val", str(val))
        assert result.returncode == 0, result.stderr


class TestGate:
    def test_missing_report_fails(self, tmp_path: Path) -> None:
        result = qa_check.run(tmp_path / "nope.json", max_age_hours=0)
        assert result["status"] == "fail"
        assert any(c["name"] == "eval_report" and not c["ok"] for c in result["checks"])

    def test_report_that_scored_nothing_fails(self, tmp_path: Path) -> None:
        # A report with zero scored examples must never read as a pass: it
        # looks like coverage and is not.
        report = tmp_path / "empty.json"
        report.write_text(json.dumps({"summary": {"scored": 0, "request_errors": 0}}))
        result = qa_check.run(report, max_age_hours=0)
        assert result["status"] == "fail"
        assert any(c["name"] == "eval_scored" and not c["ok"] for c in result["checks"])

    def test_threshold_below_target_fails(self, tmp_path: Path) -> None:
        report = tmp_path / "bad.json"
        report.write_text(
            json.dumps(
                {
                    "summary": {
                        "scored": 10,
                        "request_errors": 0,
                        "exact_match": 0.1,
                        "parse_error_rate": 0.0,
                        "latency_ms": {"p95": 100},
                    }
                }
            )
        )
        result = qa_check.run(report, max_age_hours=0)
        failed = [c for c in result["checks"] if c["name"].startswith("threshold:") and not c["ok"]]
        assert failed, "a 10% accuracy report should fail the committed thresholds"

    def test_resolve_walks_dotted_paths(self) -> None:
        report = {"summary": {"latency_ms": {"p95": 42}}}
        assert qa_check.resolve(report, "summary.latency_ms.p95") == 42
        assert qa_check.resolve(report, "summary.missing.key") is None
