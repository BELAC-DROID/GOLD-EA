"""
Phase 3, Test 1, Metric G: Session-Open Behavior (opening-range prediction)

Same structure as Metric A (percentage-of-prior-close prediction vs
naive lag-1), but scoped to just the first 30 minutes of each session
rather than the full session range - tests whether the "volatility
expansion at open" pattern is itself predictable, not just present.
"""

import duckdb
import numpy as np
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
SESSIONS = {"asian": (0, 8), "london": (8, 16), "ny": (13, 21)}
OPEN_WINDOW_MINUTES = 30

con = duckdb.connect(ANALYTICS_DB)


def daily_opening_data(start_h):
    start_min, end_min = start_h * 60, start_h * 60 + OPEN_WINDOW_MINUTES
    return con.execute(f"""
        WITH open_bars AS (
            SELECT date_trunc('day', minute_ts) AS day, high, low
            FROM minute_bars_ohlc
            WHERE minute_of_day >= {start_min} AND minute_of_day < {end_min}
              AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        ),
        open_range AS (
            SELECT day, (max(high) - min(low)) AS opening_range
            FROM open_bars GROUP BY day HAVING count(*) > {OPEN_WINDOW_MINUTES * 0.5}
        ),
        daily_close AS (
            SELECT date_trunc('day', minute_ts) AS day, arg_max(close, minute_ts) AS day_close
            FROM minute_bars_ohlc GROUP BY day
        ),
        with_prior AS (
            SELECT day, day_close, LAG(day_close) OVER (ORDER BY day) AS prior_close
            FROM daily_close
        )
        SELECT r.day, r.opening_range, p.prior_close
        FROM open_range r JOIN with_prior p ON p.day = r.day
        WHERE p.prior_close IS NOT NULL
        ORDER BY r.day
    """).fetchdf()


for name, (start_h, end_h) in SESSIONS.items():
    df = daily_opening_data(start_h)
    print(f"\n{'='*70}\nSession: {name} (first {OPEN_WINDOW_MINUTES} min)\n{'='*70}")
    for combo in COMBOS:
        splits = generate_splits(combo)
        model_errors, naive_errors = [], []
        for s in splits:
            train = df[(df["day"] >= s["train_start"]) & (df["day"] <= s["train_end"])]
            test = df[(df["day"] >= s["test_start"]) & (df["day"] <= s["test_end"])].reset_index(drop=True)
            if len(train) == 0 or len(test) < 2:
                continue
            train_ratio = (train["opening_range"] / train["prior_close"]).mean()
            preds = train_ratio * test["prior_close"].values
            actual = test["opening_range"].values
            model_errors.extend(np.abs(actual - preds))
            naive_errors.extend(np.abs(actual[1:] - actual[:-1]))
        if not model_errors:
            print(f"  {combo['name']:25s}  no valid folds")
            continue
        model_mae = np.mean(model_errors)
        naive_mae = np.mean(naive_errors) if naive_errors else float("nan")
        flag = "beats naive" if model_mae < naive_mae else "worse than naive"
        print(f"  {combo['name']:25s}  n={len(model_errors):5d}  model_MAE={model_mae:.4f}  "
              f"naive_MAE={naive_mae:.4f}  -> {flag}")