"""
Phase 3, Test 1 Metric A revision: percentage-based range prediction.

Motivated by the original walk-forward test's Split 3 failure: a model
predicting a fixed DOLLAR range (learned from 2019-2024, when gold
traded $1,300-2,600) badly underestimated 2025 ranges once price moved
into the $3,000-3,700+ range - the same fixed-absolute-value problem
that also broke level_reaction.py's spacing (see level_reaction_v2.py
and check_level_spacing_by_price.py).

Fix: predict range as a PERCENTAGE of price (learned from train period),
then convert to dollars using a known, non-lookahead price reference -
yesterday's closing price - rather than the test day's own price
(which wouldn't be known in advance).

Uses the now-rebuilt, verified minute_bars_ohlc (covers through
2025-12-31) directly, rather than rescanning raw ticks.

Reports THREE comparisons per split: the original fixed-dollar model,
this percentage-based model, and the naive lag-1 baseline - so the fix
can be judged against both the old approach and naive, not just naive.
"""

import duckdb
import numpy as np

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60

SESSIONS = {
    "asian":  (0, 8),
    "london": (8, 16),
    "ny":     (13, 21),
}

SPLITS = [
    ("2019-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("2019-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
    ("2019-01-01", "2024-12-31", "2025-01-01", None),
]

N_BOOTSTRAP = 2000
RNG = np.random.default_rng(42)

con = duckdb.connect(ANALYTICS_DB)


def daily_session_data(start_h, end_h):
    """One row per day: (day, day_range, prior_close), prior_close = previous
    calendar day's last close from minute_bars_ohlc (known before today starts)."""
    start_min, end_min = start_h * 60, end_h * 60
    df = con.execute(f"""
        WITH session_bars AS (
            SELECT date_trunc('day', minute_ts) AS day, high, low
            FROM minute_bars_ohlc
            WHERE minute_of_day >= {start_min} AND minute_of_day < {end_min}
              AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        ),
        session_range AS (
            SELECT day, (max(high) - min(low)) AS day_range
            FROM session_bars
            GROUP BY day
            HAVING count(*) > 30
        ),
        daily_close AS (
            SELECT date_trunc('day', minute_ts) AS day, arg_max(close, minute_ts) AS day_close
            FROM minute_bars_ohlc
            GROUP BY day
        ),
        with_prior AS (
            SELECT day, day_close, LAG(day_close) OVER (ORDER BY day) AS prior_close
            FROM daily_close
        )
        SELECT r.day, r.day_range, p.prior_close
        FROM session_range r
        JOIN with_prior p ON p.day = r.day
        WHERE p.prior_close IS NOT NULL
        ORDER BY r.day
    """).fetchdf()
    return df


def bootstrap_mae_ci(errors, n=N_BOOTSTRAP):
    errors = np.array(errors)
    boots = [np.mean(RNG.choice(errors, size=len(errors), replace=True)) for _ in range(n)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return lo, hi


def run_split(df, train_start, train_end, test_start, test_end):
    train = df[(df["day"] >= train_start) & (df["day"] <= train_end)]
    if test_end is None:
        test = df[df["day"] >= test_start].reset_index(drop=True)
    else:
        test = df[(df["day"] >= test_start) & (df["day"] <= test_end)].reset_index(drop=True)

    if len(train) == 0 or len(test) < 2:
        return None

    # OLD model: fixed dollar mean range, learned from train
    fixed_dollar_pred = train["day_range"].mean()

    # NEW model: mean of (range / prior_close) ratio, learned from train,
    # applied to each test day's own prior_close (known, non-lookahead)
    train_ratio = (train["day_range"] / train["prior_close"]).mean()
    pct_preds = train_ratio * test["prior_close"].values

    actual = test["day_range"].values
    fixed_errors = np.abs(actual - fixed_dollar_pred)
    pct_errors = np.abs(actual - pct_preds)

    # naive: yesterday's actual test-period range
    naive_errors = np.abs(actual[1:] - actual[:-1])

    fixed_mae = float(np.mean(fixed_errors))
    pct_mae = float(np.mean(pct_errors))
    naive_mae = float(np.mean(naive_errors))
    pct_ci = bootstrap_mae_ci(pct_errors)

    return {
        "n_test_days": len(test),
        "train_ratio_pct": round(train_ratio * 100, 3),
        "fixed_dollar_mae": round(fixed_mae, 3),
        "pct_model_mae": round(pct_mae, 3),
        "pct_model_mae_95ci": (round(pct_ci[0], 3), round(pct_ci[1], 3)),
        "naive_mae": round(naive_mae, 3),
        "pct_beats_naive": pct_mae < naive_mae,
        "pct_beats_fixed_dollar": pct_mae < fixed_mae,
    }


for split_i, (train_start, train_end, test_start, test_end) in enumerate(SPLITS, 1):
    test_label = test_end if test_end else "latest available"
    print(f"=== Split {split_i}: train {train_start}->{train_end}, test {test_start}->{test_label} ===")
    for name, (start_h, end_h) in SESSIONS.items():
        df = daily_session_data(start_h, end_h)
        result = run_split(df, train_start, train_end, test_start, test_end)
        if result is None:
            print(f"  {name:8s}  insufficient data")
            continue
        f1 = "beats naive" if result["pct_beats_naive"] else "worse than naive"
        f2 = "beats old fixed-$ model" if result["pct_beats_fixed_dollar"] else "worse than old fixed-$ model"
        print(f"  {name:8s}  train_ratio={result['train_ratio_pct']}% of prior close")
        print(f"           pct-model MAE={result['pct_model_mae']:6.3f} (95% CI {result['pct_model_mae_95ci']})  "
              f"-> {f1}, {f2}")
        print(f"           (for reference: old fixed-$ MAE={result['fixed_dollar_mae']:6.3f}, "
              f"naive MAE={result['naive_mae']:6.3f})")
    print()