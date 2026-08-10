"""Starter tests for <name>'s backtest pipeline.

Unit-tests the pure computation paths (compute_metrics) with real inputs
and asserts on real outputs. The end-to-end run against fixtures is
covered by the `run-backtest` CI job which invokes `docker run` and
asserts the schema of the generated metrics.json — these tests protect
the faster-to-run inner logic.
"""

from __future__ import annotations

from typing import Any

from backtest import compute_metrics

_PARAMS: dict[str, Any] = {"backtest": {"initial_capital": 10_000}}


def _fake_trades(n_wins: int, n_losses: int) -> list[dict[str, Any]]:
    """Build a deterministic trade log with the requested win/loss mix."""
    trades: list[dict[str, Any]] = []
    for _i in range(n_wins):
        trades.append(
            {
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-10",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "pnl_pct": 0.10,
                "pnl_dollars": 100.0,
                "symbol": "TEST",
            }
        )
    for _i in range(n_losses):
        trades.append(
            {
                "entry_date": "2025-02-01",
                "exit_date": "2025-02-10",
                "entry_price": 100.0,
                "exit_price": 95.0,
                "pnl_pct": -0.05,
                "pnl_dollars": -50.0,
                "symbol": "TEST",
            }
        )
    return trades


def test_compute_metrics_zero_trades_returns_failure_flag() -> None:
    m = compute_metrics([], _PARAMS)
    assert m["success"] is False
    assert m["trades_count"] == 0
    # Even on failure, the schema must be consistent — review_pr depends on it
    for key in (
        "win_rate",
        "total_return_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
        "avg_pnl_pct",
    ):
        assert key in m, f"metrics.json must always include {key}"


def test_compute_metrics_all_wins_is_100_percent_win_rate() -> None:
    m = compute_metrics(_fake_trades(n_wins=5, n_losses=0), _PARAMS)
    assert m["success"] is True
    assert m["trades_count"] == 5
    assert m["win_rate"] == 1.0
    assert m["total_return_dollars"] == 500.0


def test_compute_metrics_all_losses_is_0_percent_win_rate() -> None:
    m = compute_metrics(_fake_trades(n_wins=0, n_losses=4), _PARAMS)
    assert m["success"] is True
    assert m["win_rate"] == 0.0
    assert m["total_return_dollars"] == -200.0


def test_compute_metrics_mixed_trades_match_expected_math() -> None:
    m = compute_metrics(_fake_trades(n_wins=3, n_losses=2), _PARAMS)
    assert m["trades_count"] == 5
    assert m["win_rate"] == 3 / 5
    # 3 wins at $100 = $300, 2 losses at -$50 = -$100, net = $200
    assert m["total_return_dollars"] == 200.0
    # avg pnl pct: (0.10 + 0.10 + 0.10 + -0.05 + -0.05) / 5 = 0.04
    assert abs(m["avg_pnl_pct"] - 0.04) < 1e-9


def test_compute_metrics_schema_matches_ci_assertions() -> None:
    # This set of keys is what the CI job asserts exists in metrics.json.
    # If compute_metrics ever drops one, CI will fail — but so will this
    # test, which fails faster and gives a clearer error.
    required = {
        "success",
        "win_rate",
        "sharpe_ratio",
        "max_drawdown_pct",
        "total_return_pct",
        "trades_count",
    }
    m = compute_metrics(_fake_trades(2, 2), _PARAMS)
    missing = required - set(m.keys())
    assert not missing, f"metrics.json missing keys: {missing}"
