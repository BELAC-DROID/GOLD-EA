"""
Phase 3, Test 1, Metric E: Distribution Shape Stability

Checks whether train-period skew/kurtosis of daily session returns
(pct of prior close) matches test-period realized skew/kurtosis, across
the window matrix. Unlike other metrics, this isn't a classifier -
it's a direct distributional-transfer check, reported per split rather
than scored against a naive baseline (no natural naive exists here).
"""

import duckdb
import numpy as np
from scipy import stats
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
SESSIONS = {"asian": (0, 8), "london": (8, 16), "ny": (13, 21)}

con = duckdb.connect(ANALYTICS_DB)


def daily_session_ratio(start_h, end_h):
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
        SELECT r.day, r.day_range / p.prior_close AS ratio
        FROM session_range r JOIN with_prior p ON p.day = r.day
        WHERE p.prior_close IS NOT NULL
        ORDER BY r.day
    """).fetchdf()


for name, (start_h, end_h) in SESSIONS.items():
    df = daily_session_ratio(start_h, end_h)
    print(f"\n{'='*70}\nSession: {name}\n{'='*70}")
    for combo in COMBOS:
        splits = generate_splits(combo)
        print(f"\n  --- {combo['name']} ---")
        skew_diffs, kurt_diffs = [], []
        for s in splits:
            train = df[(df["day"] >= s["train_start"]) & (df["day"] <= s["train_end"])]["ratio"]
            test = df[(df["day"] >= s["test_start"]) & (df["day"] <= s["test_end"])]["ratio"]
            if len(train) < 30 or len(test) < 30:
                continue
            train_skew, test_skew = stats.skew(train), stats.skew(test)
            train_kurt, test_kurt = stats.kurtosis(train), stats.kurtosis(test)
            skew_diffs.append(abs(train_skew - test_skew))
            kurt_diffs.append(abs(train_kurt - test_kurt))
            print(f"    fold {s['test_start']}->{s['test_end']}:  "
                  f"train_skew={train_skew:.3f} test_skew={test_skew:.3f}  |  "
                  f"train_kurt={train_kurt:.3f} test_kurt={test_kurt:.3f}")
        if skew_diffs:
            print(f"    avg |skew diff|={np.mean(skew_diffs):.3f}  avg |kurt diff|={np.mean(kurt_diffs):.3f}")