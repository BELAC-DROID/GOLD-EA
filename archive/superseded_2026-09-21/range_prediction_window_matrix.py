"""
Applies the pre-committed window matrix (walk_forward_matrix.py) to the
percentage-based range prediction model. Reuses the exact model logic
from test1_range_prediction_v2.py - only the split generation changes.

Per combo: pools errors across ALL folds (not just one split), reports
aggregate MAE vs naive, per session.
"""

import duckdb
import numpy as np
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60

SESSIONS = {"asian": (0, 8), "london": (8, 16), "ny": (13, 21)}

con = duckdb.connect(ANALYTICS_DB)


def daily_session_data(start_h, end_h):
    start_min, end_min = start_h * 60, end_h * 60
    return con.execute(f"""
        WITH session_bars AS (
            SELECT date_trunc('day', minute_ts) AS day, high, low
            FROM minute_bars_ohlc
            WHERE minute_of_day >= {start_min} AND minute_of_day < {end_min}
              AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        ),
        session_range AS (
            SELECT day, (max(high) - min(low)) AS day_range
            FROM session_bars GROUP BY day HAVING count(*) > 30
        ),
        daily_close AS (
            SELECT date_trunc('day', minute_ts) AS day, arg_max(close, minute_ts) AS day_close
            FROM minute_bars_ohlc GROUP BY day
        ),
        with_prior AS (
            SELECT day, day_close, LAG(day_close) OVER (ORDER BY day) AS prior_close
            FROM daily_close
        )
        SELECT r.day, r.day_range, p.prior_close
        FROM session_range r JOIN with_prior p ON p.day = r.day
        WHERE p.prior_close IS NOT NULL
        ORDER BY r.day
    """).fetchdf()


for name, (start_h, end_h) in SESSIONS.items():
    df = daily_session_data(start_h, end_h)
    print(f"\n=== Session: {name} ===")
    for combo in COMBOS:
        splits = generate_splits(combo)
        pct_errors_all, naive_errors_all = [], []
        for s in splits:
            train = df[(df["day"] >= s["train_start"]) & (df["day"] <= s["train_end"])]
            test = df[(df["day"] >= s["test_start"]) & (df["day"] <= s["test_end"])].reset_index(drop=True)
            if len(train) == 0 or len(test) < 2:
                continue
            train_ratio = (train["day_range"] / train["prior_close"]).mean()
            preds = train_ratio * test["prior_close"].values
            actual = test["day_range"].values
            pct_errors_all.extend(np.abs(actual - preds))
            naive_errors_all.extend(np.abs(actual[1:] - actual[:-1]))
        if not pct_errors_all:
            print(f"  {combo['name']:25s}  no valid folds")
            continue
        pct_mae = np.mean(pct_errors_all)
        naive_mae = np.mean(naive_errors_all) if naive_errors_all else float("nan")
        flag = "beats naive" if pct_mae < naive_mae else "worse than naive"
        print(f"  {combo['name']:25s}  n_folds={len(splits):2d}  pooled_test_days={len(pct_errors_all):5d}  "
              f"pct_MAE={pct_mae:6.3f}  naive_MAE={naive_mae:6.3f}  -> {flag}")