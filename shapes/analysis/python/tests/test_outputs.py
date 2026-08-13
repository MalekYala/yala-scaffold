"""Starter tests for <name>'s analysis.

Covers the pure-function `analyze()` with a small DataFrame so the
inner logic is protected without reading fixtures from disk. The
end-to-end run (load_input → analyze → write_outputs → qa_check) is
covered by the CI job that actually invokes the container.
"""

from __future__ import annotations

import pandas as pd

from analyze import analyze


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "a": [1, 2, 3, 4, 5],
            "b": [10.0, 20.0, 30.0, 40.0, 50.0],
            "label": ["x", "y", "x", "y", "x"],
        }
    )


def test_analyze_reports_correct_row_count() -> None:
    summary = analyze(_sample_df())
    assert summary["row_count"] == 5


def test_analyze_reports_correct_column_count() -> None:
    summary = analyze(_sample_df())
    assert summary["column_count"] == 3


def test_analyze_reports_all_columns() -> None:
    summary = analyze(_sample_df())
    assert set(summary["columns"]) == {"a", "b", "label"}


def test_analyze_empty_dataframe_does_not_crash() -> None:
    # Empty DataFrames are a common footgun — analyze() must not throw.
    summary = analyze(pd.DataFrame())
    assert summary["row_count"] == 0
    assert summary["column_count"] == 0
    assert summary["columns"] == []
