"""
Phase 3, Test 1, Metric H: Anomaly-Flagging Precision (opening-range half)

Flag: today's first-30-min range exceeds the 90th percentile of a
trailing rolling window of prior opening ranges (causal, recomputed
continuously - same percentile-rank discipline as Metric C, no fixed
boundary).

Ground truth: does the FULL session's range regime land in "high" per
Metric C's definition (top 20th percentile of trailing range ratio)?
Reuses that exact labeling logic so results are directly comparable.

Scored as precision: P(actual_high | flagged) vs the unconditional
base rate P(actual_high) - the natural naive baseline here, since a
flag with no real signal should match the base rate exactly.

NOTE: this covers only the volatility-spike half of anomaly-flagging.
The calendar-proximity half (does proximity to a high-impact event
predict a confirmed anomaly) is deliberately NOT built here - it needs
spread_model.py's exact curated event whitelist, which I don't have in
hand, and I'm not reconstructing it from memory given how costly
guessing at existing logic has been earlier this session.
"""

import duckdb
import numpy as np
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
SESSIONS = {"asian": (0, 8), "london": (8, 16), "ny": (13, 21)}
OPEN_WINDOW_MINUTES = 30
OPEN_ANOMALY_PCTL = 90
FULL_DAY_LOOKBACK = 100  # matches Metric C's default
FULL_DAY_HIGH_PCTL = 80  # matches Metric C's "high" cutoff

con = duckdb.connect(ANALYTICS_DB)


def daily_data(start_h, end_h):
    start_min, end_min = start_h * 60, end_h * 60
    open_end_min = start_min + OPEN_WINDOW_MINUTES
    return con.execute(f"""
        WITH full_bars AS (
            SELECT date_trunc('day', minute_ts) AS day, high, low
            FROM minute_bars_ohlc
            WHERE minute_of_day >= {start_min} AND minute_of_day < {end_min}
              AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        ),
        full_range AS (
            SELECT day, (max(high) - min(low)) AS day_range
            FROM full_bars GROUP BY day HAVING count(*) > 30
        ),
        open_bars AS (
            SELECT date_trunc('day', minute_ts) AS day, high, low
            FROM minute_bars_ohlc
            WHERE minute_of_day >= {start_min} AND minute_of_day < {open_end_min}
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
        SELECT f.day, f.day_range / p.prior_close AS day_ratio,
               o.opening_range / p.prior_close AS open_ratio
        FROM full_range f
        JOIN open_range o ON o.day = f.day
        JOIN with_prior p ON p.day = f.day
        WHERE p.prior_close IS NOT NULL
        ORDER BY f.day
    """).fetchdf()


def label(df):
    day_ratio = df["day_ratio"].values
    open_ratio = df["open_ratio"].values
    n = len(df)
    actual_high = [None] * n
    flagged = [None] * n
    for i in range(FULL_DAY_LOOKBACK, n):
        day_window = day_ratio[i - FULL_DAY_LOOKBACK:i]
        day_hi = np.percentile(day_window, FULL_DAY_HIGH_PCTL)
        actual_high[i] = day_ratio[i] > day_hi

        open_window = open_ratio[i - FULL_DAY_LOOKBACK:i]
        open_hi = np.percentile(open_window, OPEN_ANOMALY_PCTL)
        flagged[i] = open_ratio[i] > open_hi
    df = df.copy()
    df["actual_high"] = actual_high
    df["flagged"] = flagged
    return df.dropna(subset=["actual_high", "flagged"])


for name, (start_h, end_h) in SESSIONS.items():
    df = label(daily_data(start_h, end_h))
    print(f"\n{'='*70}\nSession: {name}\n{'='*70}")
    for combo in COMBOS:
        splits = generate_splits(combo)
        all_flagged_actual = []
        all_base_actual = []
        for s in splits:
            test = df[(df["day"] >= s["test_start"]) & (df["day"] <= s["test_end"])]
            if len(test) < 10:
                continue
            all_base_actual.extend(test["actual_high"].tolist())
            flagged_rows = test[test["flagged"] == True]
            all_flagged_actual.extend(flagged_rows["actual_high"].tolist())
        if not all_flagged_actual:
            print(f"  {combo['name']:25s}  no flagged days in test period")
            continue
        precision = np.mean(all_flagged_actual)
        base_rate = np.mean(all_base_actual)
        flag = "BEATS base rate" if precision > base_rate else "does NOT beat base rate"
        print(f"  {combo['name']:25s}  n_flagged={len(all_flagged_actual):4d}  "
              f"precision={precision:.3f}  base_rate={base_rate:.3f}  -> {flag}")