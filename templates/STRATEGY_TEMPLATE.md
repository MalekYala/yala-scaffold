# <name> — Strategy

> **Written at project kick-off. Updated when the strategy changes.**
> This is the source of truth for *what* this project is trying to accomplish
> and *how* success is measured. Every line of code, every KPI, every test,
> and every autoresearch iteration should trace back to something in this doc.
>
> Committed to git. Public-safe — describe the shape of the work, not
> operator-specific deployment details (those go in `LOCAL.md`).

---

## 1. Problem statement

*(One paragraph: what is this project for? What need does it serve? Who or
what is the user/consumer of the output?)*

> Example (backtest): "We want to know whether the 50/200-day SMA crossover
> strategy described in the attached PDF actually beats buy-and-hold over the
> last 10 years across the S&P 500 constituents. The consumer is the fund
> manager evaluating which signals to add to the paper-trading book."

## 2. Shape

**Shape:** `<shape>`  *(one of: service, worker, analysis, backtest, report, notebook, pipeline)*

**Why this shape:** *(What about the problem makes this the right fit?)*

**Long-running?** *(yes = restarts on failure, exposes state; no = runs to completion and exits)*

## 3. Inputs

*(What does this project consume? List every input, where it comes from, its
format, and whether it's committed to the repo or operator-supplied.)*

| Input | Source | Format | Committed? | Notes |
|---|---|---|---|---|
| *(example: daily OHLCV)* | Polygon API via `DATA_PATH` env var | parquet | no (operator) | `fixtures/sample_ohlcv.parquet` committed for CI |
| *(example: strategy params)* | `config/strategy.yml` | YAML | yes | autoresearch iterates on this |

## 4. Outputs

*(What does this project produce? List every artifact, where it lands, and
who consumes it.)*

| Output | Path | Format | Consumed by | Notes |
|---|---|---|---|---|
| *(example: equity curve)* | `outputs/equity_curve.pdf` | PDF | fund manager | regenerated each run |
| *(example: metrics summary)* | `results/metrics.json` | JSON | KPI collector, CI | schema in `docs/API.md` |

## 5. Success metric

**Primary metric:** *(the single number that answers "did this work?")*

**How it's computed:** *(point to the code or describe the formula)*

**Target value:** *(what threshold counts as success?)*

**Direction:** *(higher is better / lower is better)*

> Example (backtest): Primary metric is **annualized Sharpe ratio** over the
> 10-year backtest. Computed in `backtest/metrics.py::sharpe()`. Target ≥ 1.0.
> Direction: higher is better. Secondary metrics tracked in `kpi.json`:
> win_rate, max_drawdown, total_return_pct.

## 6. Iteration loop (autoresearch)

If this project uses `make iterate` to autonomously improve the metric, fill
this section in. Otherwise write "N/A — no iteration loop".

- **What gets varied?** *(e.g., strategy parameters, prompt wording, model
  choice, feature set)*
- **Search space:** *(bounds on each variable)*
- **Metric function:** *(`metric.sh` prints what float?)*
- **Stop condition:** *(metric ≥ target, iterations ≥ N, manual `STOP_AUTORESEARCH`)*
- **Verify gates:** *(what must still pass — qa_check.py, existing test fixtures, no NaN in outputs)*

## 7. Out of scope

*(What is this project deliberately **not** doing? Listing these up-front
prevents scope creep and tells reviewers "don't ask me to add this".)*

- *(example: live trading — this is backtest-only)*
- *(example: intraday data — daily bars only)*
- *(example: transaction cost modeling beyond a flat 5bp slippage)*

## 8. Non-obvious assumptions

*(Things the agent assumed that someone else might question. Document them
now; future-you will not remember why.)*

- *(example: survivorship bias is acceptable because we're evaluating relative
  performance vs. buy-and-hold, not absolute alpha)*
- *(example: splits and dividends handled by the data provider; we don't
  re-adjust)*

## 9. Related docs

- [`README.md`](README.md) — quickstart + overview
- [`AGENTS.md`](AGENTS.md) §0 — project shapes + strategy composition
- [`docs/SETUP.md`](docs/SETUP.md) — install and run
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — module map and design decisions
- [`kpi.json`](kpi.json) — KPIs being tracked
- [`AUTORESEARCH.md`](AUTORESEARCH.md) — iteration loop config

## Revision log

| Date | Change | Why |
|---|---|---|
| <DATE> | Initial draft | Project kick-off |
