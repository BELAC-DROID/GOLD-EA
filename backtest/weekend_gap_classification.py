"""
Phase 3, Test 1, Metric F: Weekend Gap Behavior Classification

Gap = (Monday/Sunday-reopen first price - Friday last price) / Friday
last price. Regime (small/normal/large, by absolute gap size) via
rolling percentile over trailing GAPS (not days - weekly cadence).
Tests persistence via the shared harness.

GAP_LOOKBACK=20 (~5 months of weekly gaps) is a single choice, not
swept - same scope tradeoff as Metric D.
"""

import duckdb
import numpy as np
from regime_transition_harness import run_all_combos

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
GAP_LOOKBACK = 20
REGIMES = ["small", "normal", "large"]

con = duckdb.connect(ANALYTICS_DB)

weekly = con.execute("""
    WITH daily AS (
        SELECT date_trunc('day', minute_ts) AS day,
               arg_min(close, minute_ts) AS day_open,
               arg_max(close, minute_ts) AS day_close,
               dayofweek(date_trunc('day', minute_ts)) AS dow
        FROM minute_bars_ohlc GROUP BY day
    ),
    friday_close AS (
        SELECT day AS friday, day_close AS fri_close
        FROM daily WHERE dow = 5
    ),
    next_open AS (
        SELECT d.day AS reopen_day, d.day_open AS reopen_open, d.dow
        FROM daily d WHERE d.dow IN (0, 1)  -- Sunday or Monday
    )
    SELECT f.friday, f.fri_close, n.reopen_day, n.reopen_open
    FROM friday_close f
    JOIN next_open n ON n.reopen_day = (
        SELECT min(reopen_day) FROM next_open WHERE reopen_day > f.friday
    )
    ORDER BY f.friday
""").fetchdf()

weekly["gap_abs_pct"] = ((weekly["reopen_open"] - weekly["fri_close"]).abs() / weekly["fri_close"])


def label_gap_regimes(df, lookback=GAP_LOOKBACK):
    vals = df["gap_abs_pct"].values
    regimes = [None] * len(vals)
    for i in range(lookback, len(vals)):
        window = vals[i - lookback:i]
        lo, hi = np.percentile(window, [33, 67])
        regimes[i] = "small" if vals[i] < lo else ("large" if vals[i] > hi else "normal")
    df = df.copy()
    df["regime"] = regimes
    df["prior_regime"] = df["regime"].shift(1)
    df["day"] = df["reopen_day"]  # harness expects a "day" column for split filtering
    return df.dropna(subset=["regime", "prior_regime"])


print(f"{'='*70}\nWeekend gap regime (all sessions combined - gap is a single weekly event)\n{'='*70}")
df = label_gap_regimes(weekly)
run_all_combos(df, REGIMES, "weekend_gap")