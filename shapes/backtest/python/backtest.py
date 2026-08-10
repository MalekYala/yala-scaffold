"""Strategy backtest for <name>.

Shape: backtest — loads OHLCV data, runs a strategy, computes metrics and
graphs, exits.

Required outputs:
    results/metrics.json    — headline metrics (win_rate, sharpe, etc.)
    results/trades.csv      — per-trade log
    outputs/equity_curve.png — portfolio equity over time
    outputs/drawdown.png     — drawdown chart
    outputs/trade_log.xlsx   — spreadsheet-friendly trade log

The metrics.json file is the success sentinel and is written last. Its
`win_rate` field is the default autoresearch metric (see metric.sh).

This is a minimal SMA-crossover example. Replace the `run_strategy` function
with your real strategy logic. Everything else (loading, metrics, output,
graphs) is reusable plumbing.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "info").upper()
OUTPUTS_DIR: Path = Path(os.environ.get("OUTPUTS_DIR", "outputs"))
RESULTS_DIR: Path = Path(os.environ.get("RESULTS_DIR", "results"))
DATA_DIR: Path = Path(os.environ.get("DATA_DIR", "data"))
FIXTURES_DIR: Path = Path(os.environ.get("FIXTURES_DIR", "fixtures"))
CONFIG_PATH: Path = Path(os.environ.get("CONFIG_PATH", "config/strategy.yml"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>")


def load_config() -> dict[str, Any]:
    """Load strategy + backtest parameters from YAML."""
    return yaml.safe_load(CONFIG_PATH.read_text())  # type: ignore[no-any-return]


def load_ohlcv(symbol: str) -> pd.DataFrame:
    """Load OHLCV data for a symbol.

    Tries DATA_DIR first (real data), falls back to FIXTURES_DIR for CI.
    Expected schema: date, open, high, low, close, volume.
    """

    for base in (DATA_DIR, FIXTURES_DIR):
        for name in (f"{symbol}.csv", f"{symbol}.parquet"):
            p = base / name
            if p.exists():
                log.info(f"loading {symbol} from {p}")
                df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p, parse_dates=["date"])
                df = df.sort_values("date").reset_index(drop=True)
                return df
    raise FileNotFoundError(f"no OHLCV data for {symbol} in {DATA_DIR} or {FIXTURES_DIR}")


def run_strategy(df: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the strategy and return a list of trade dicts.

    Each trade dict must have: entry_date, exit_date, entry_price, exit_price,
    pnl_pct, pnl_dollars, symbol. Add whatever else is useful for analysis.

    This is a minimal SMA-crossover example. Replace with your real strategy.
    """
    short_w = int(params["strategy"]["short_window"])
    long_w = int(params["strategy"]["long_window"])
    position_size = float(params["strategy"]["position_size"])
    initial_capital = float(params["backtest"]["initial_capital"])
    cost_bps = float(params["backtest"]["cost_bps"])

    df = df.copy()
    df["short_sma"] = df["close"].rolling(short_w).mean()
    df["long_sma"] = df["close"].rolling(long_w).mean()
    df["signal"] = (df["short_sma"] > df["long_sma"]).astype(int)
    df["position"] = df["signal"].diff().fillna(0)  # +1 entry, -1 exit

    trades: list[dict[str, Any]] = []
    in_position = False
    entry_date: Any = None
    entry_price: float | None = None
    symbol = df.get("symbol", ["?"] * len(df))[0] if "symbol" in df.columns else "?"

    for _, row in df.iterrows():
        if row["position"] == 1 and not in_position:
            in_position = True
            entry_date = row["date"]
            entry_price = row["close"]
        elif row["position"] == -1 and in_position and entry_price is not None:
            exit_price = row["close"]
            gross_pnl_pct = (exit_price - entry_price) / entry_price
            net_pnl_pct = gross_pnl_pct - 2 * cost_bps / 10_000
            pnl_dollars = initial_capital * position_size * net_pnl_pct
            trades.append(
                {
                    "symbol": symbol,
                    "entry_date": str(entry_date),
                    "exit_date": str(row["date"]),
                    "entry_price": float(entry_price),
                    "exit_price": float(exit_price),
                    "pnl_pct": float(net_pnl_pct),
                    "pnl_dollars": float(pnl_dollars),
                }
            )
            in_position = False

    return trades


def compute_metrics(trades: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    """Compute headline backtest metrics from the trade log.

    Returns a dict with: win_rate, total_return_pct, total_return_dollars,
    sharpe_ratio (annualized, daily bars), max_drawdown_pct, trades_count,
    avg_pnl_pct, and a `success` flag.
    """
    import numpy as np

    if not trades:
        return {
            "success": False,
            "error": "no trades generated — strategy may be too restrictive",
            "trades_count": 0,
            "win_rate": 0.0,
            "total_return_pct": 0.0,
            "total_return_dollars": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_pnl_pct": 0.0,
        }

    pnl_pcts = np.array([t["pnl_pct"] for t in trades])
    pnl_dollars = np.array([t["pnl_dollars"] for t in trades])
    equity = np.cumsum(pnl_dollars) + params["backtest"]["initial_capital"]

    wins = int((pnl_pcts > 0).sum())
    win_rate = wins / len(trades)
    total_return_dollars = float(pnl_dollars.sum())
    total_return_pct = total_return_dollars / params["backtest"]["initial_capital"]

    sharpe = 0.0
    if pnl_pcts.std() > 0:
        # Assume each trade is ~N days; rough annualized Sharpe
        sharpe = float(pnl_pcts.mean() / pnl_pcts.std() * np.sqrt(252 / 20))

    # Max drawdown from equity curve
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0

    return {
        "success": True,
        "trades_count": len(trades),
        "win_rate": float(win_rate),
        "total_return_pct": float(total_return_pct),
        "total_return_dollars": total_return_dollars,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_dd,
        "avg_pnl_pct": float(pnl_pcts.mean()),
    }


def write_outputs(
    trades: list[dict[str, Any]],
    metrics: dict[str, Any],
    params: dict[str, Any],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # results/metrics.json — success sentinel + headline metrics
    (RESULTS_DIR / "metrics.json").write_text(
        json.dumps(
            {
                **metrics,
                "timestamp": int(time.time()),
                "params": params,
            },
            indent=2,
            default=str,
        )
    )
    log.info(f"wrote {RESULTS_DIR}/metrics.json")

    if not trades:
        log.warning("no trades — skipping trade log and graphs")
        return

    df_trades = pd.DataFrame(trades)

    # results/trades.csv
    df_trades.to_csv(RESULTS_DIR / "trades.csv", index=False)

    # outputs/trade_log.xlsx — human-friendly
    df_trades.to_excel(OUTPUTS_DIR / "trade_log.xlsx", index=False)

    # outputs/equity_curve.png
    equity = np.cumsum([t["pnl_dollars"] for t in trades]) + params["backtest"]["initial_capital"]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(range(len(equity)), equity, color="#1f77b4")
    ax.set_title(f"<name> — Equity Curve (win rate {metrics['win_rate']:.1%})")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Equity (USD)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUTS_DIR / "equity_curve.png", dpi=100)
    plt.close(fig)

    # outputs/drawdown.png
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak * 100
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(range(len(drawdown)), drawdown, 0, color="#d62728", alpha=0.5)
    ax.set_title("<name> — Drawdown")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUTS_DIR / "drawdown.png", dpi=100)
    plt.close(fig)

    log.info("wrote outputs/equity_curve.png, outputs/drawdown.png, outputs/trade_log.xlsx")


def main() -> None:
    _t_total = time.monotonic()
    log.info("<name> backtest starting")

    params = load_config()
    log.info(f"strategy params: {params['strategy']}")

    all_trades: list[dict[str, Any]] = []
    for symbol in params["backtest"]["symbols"]:
        _t = time.monotonic()
        df = load_ohlcv(symbol)
        _load_ms = int((time.monotonic() - _t) * 1000)
        log.info(f"[<name>-perf] phase=load_{symbol} duration_ms={_load_ms} bars={len(df)}")

        _t = time.monotonic()
        trades = run_strategy(df, params)
        _strat_ms = int((time.monotonic() - _t) * 1000)
        log.info(f"[<name>-perf] phase=strategy_{symbol} duration_ms={_strat_ms} trades={len(trades)}")
        all_trades.extend(trades)

    _t = time.monotonic()
    metrics = compute_metrics(all_trades, params)
    log.info(f"[<name>-perf] phase=metrics duration_ms={int((time.monotonic() - _t) * 1000)}")

    log.info(
        f"results: trades={metrics['trades_count']} "
        f"win_rate={metrics['win_rate']:.1%} "
        f"return={metrics['total_return_pct']:.1%} "
        f"sharpe={metrics['sharpe_ratio']:.2f} "
        f"max_dd={metrics['max_drawdown_pct']:.1%}"
    )

    _t = time.monotonic()
    write_outputs(all_trades, metrics, params)
    log.info(f"[<name>-perf] phase=write duration_ms={int((time.monotonic() - _t) * 1000)}")

    log.info(f"[<name>-perf] phase=total duration_ms={int((time.monotonic() - _t_total) * 1000)} status=ok")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.exception(f"backtest failed: {exc}")
        sys.exit(1)
    sys.exit(0)
