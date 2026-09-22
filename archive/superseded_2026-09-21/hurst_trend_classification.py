"""
Phase 3, Test 1, Metric D: Hurst Exponent / Trend Character Classification

Computes a rolling Hurst exponent (R/S analysis) on daily log returns
per session, buckets into trending (H>0.55) / mean-reverting (H<0.45) /
random-walk (else), and tests whether the regime persists day-to-day
using the shared regime_transition_harness.

Log returns are used throughout (not price levels or dollar changes) -
inherently regime-shift-safe, no fixed-dollar assumption possible here.
"""

import duckdb
import numpy as np
from regime_transition_harness import run_all_combos

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
SESSIONS = {"asian": (0, 8), "london": (8, 16), "ny": (13, 21)}
HURST_LOOKBACK = 60  # trading days of returns per R/S calculation
REGIMES = ["trending", "mean_reverting", "random"]

con = duckdb.connect(ANALYTICS_DB)


def daily_session_close(start_h, end_h):
    start_min, end_min = start_h * 60, end_h * 60
    return con.execute(f"""
        WITH session_bars AS (
            SELECT date_trunc('day', minute_ts) AS day, close, minute_ts
            FROM minute_bars_ohlc
            WHERE minute_of_day >= {start_min} AND minute_of_day < {end_min}
              AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        )
        SELECT day, arg_max(close, minute_ts) AS day_close
        FROM session_bars GROUP BY day ORDER BY day
    """).fetchdf()
"""
Phase 3, Test 1, Metric D (v2): Hurst / Trend Character Classification

Fix from v1: testing DAY-TO-DAY transitions with a 60-day overlapping
Hurst window meant ~87% of consecutive labels were mechanically
identical (only 1/60 of the underlying return data changes day to
day) - "beats majority" was mostly re-discovering window overlap, not
real trend-character persistence. Fixed by testing transitions STRIDE
days apart instead of 1 day apart, so compared windows share much less
overlapping data - a genuine persistence question, not a stickiness
artifact.
"""

import duckdb
import numpy as np
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
SESSIONS = {"asian": (0, 8), "london": (8, 16), "ny": (13, 21)}
HURST_LOOKBACK = 60
STRIDE_DAYS = 20  # compare regimes this many days apart, not 1
REGIMES = ["trending", "mean_reverting", "random"]

con = duckdb.connect(ANALYTICS_DB)


def daily_session_close(start_h, end_h):
    start_min, end_min = start_h * 60, end_h * 60
    return con.execute(f"""
        WITH session_bars AS (
            SELECT date_trunc('day', minute_ts) AS day, close, minute_ts
            FROM minute_bars_ohlc
            WHERE minute_of_day >= {start_min} AND minute_of_day < {end_min}
              AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        )
        SELECT day, arg_max(close, minute_ts) AS day_close
        FROM session_bars GROUP BY day ORDER BY day
    """).fetchdf()


def hurst_rs(returns):
    n = len(returns)
    if n < 20:
        return 0.5
    mean_r = np.mean(returns)
    cum_dev = np.cumsum(returns - mean_r)
    r = np.max(cum_dev) - np.min(cum_dev)
    s = np.std(returns)
    return 0.5 if s == 0 or r == 0 else np.log(r / s) / np.log(n)


def label_hurst_regimes(df, lookback=HURST_LOOKBACK):
    prices = df["day_close"].values
    log_returns = np.diff(np.log(prices))
    regimes = [None] * len(prices)
    for i in range(lookback + 1, len(prices)):
        h = hurst_rs(log_returns[i - 1 - lookback:i - 1])
        regimes[i] = "trending" if h > 0.55 else ("mean_reverting" if h < 0.45 else "random")
    df = df.copy()
    df["regime"] = regimes
    # STRIDE_DAYS apart, not 1 - the actual fix
    df["prior_regime"] = df["regime"].shift(STRIDE_DAYS)
    return df.dropna(subset=["regime", "prior_regime"])


def class_freqs(labels):
    if len(labels) == 0:
        return {r: 1 / len(REGIMES) for r in REGIMES}
    counts = {r: 0 for r in REGIMES}
    for l in labels:
        counts[l] += 1
    n = len(labels)
    return {r: counts[r] / n for r in REGIMES}


def brier(pred, actual):
    return sum((pred[r] - (1.0 if r == actual else 0.0)) ** 2 for r in REGIMES)


def run_combo(df, combo):
    splits = generate_splits(combo)
    model_scores, majority_scores = [], []
    for s in splits:
        train = df[(df["day"] >= s["train_start"]) & (df["day"] <= s["train_end"])]
        test = df[(df["day"] >= s["test_start"]) & (df["day"] <= s["test_end"])]
        if len(train) < 30 or len(test) < 10:
            continue
        transition_freqs = {r: class_freqs(train[train["prior_regime"] == r]["regime"].tolist()) for r in REGIMES}
        majority_freqs = class_freqs(train["regime"].tolist())
        for _, row in test.iterrows():
            model_pred = transition_freqs.get(row["prior_regime"], majority_freqs)
            model_scores.append(brier(model_pred, row["regime"]))
            majority_scores.append(brier(majority_freqs, row["regime"]))
    if not model_scores:
        return None
    return round(float(np.mean(model_scores)), 4), round(float(np.mean(majority_scores)), 4), len(model_scores)


for name, (start_h, end_h) in SESSIONS.items():
    print(f"\n{'='*70}\nSession: {name} (Hurst lookback={HURST_LOOKBACK}d, stride={STRIDE_DAYS}d)\n{'='*70}")
    df = label_hurst_regimes(daily_session_close(start_h, end_h))
    print(f"  regime distribution: {class_freqs(df['regime'].tolist())}")
    wins, total = 0, 0
    for combo in COMBOS:
        result = run_combo(df, combo)
        if result is None:
            print(f"    {combo['name']:25s}  no valid folds")
            continue
        model_b, maj_b, n = result
        beats = model_b < maj_b
        wins += int(beats)
        total += 1
        flag = "BEATS majority" if beats else "does not beat majority"
        print(f"    {combo['name']:25s}  n_test={n:5d}  model={model_b}  majority={maj_b}  -> {flag}")
    print(f"  Summary ({name}): beats majority in {wins}/{total} combos")