"""
Phase 3, Test 1, Metric C: Volatility Regime Classification (v2)

Fix from v1: removed the naive_persistence baseline - it made a hard
(100%-confident) single-class guess compared against soft probability
models under Brier scoring, which structurally guarantees the soft
models "win" regardless of real information content. Not a fair
comparison; model vs. naive_majority (both soft, both trained on the
same data) is the only comparison that actually isolates whether
conditioning on yesterday's regime adds real value.

Adds REGIME_LOOKBACK_DAYS as a third tested dimension (60/100/150),
per the flagged sensitivity check - a real effect should hold up
across nearby lookback lengths, not just one.
"""

import duckdb
import numpy as np
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
SESSIONS = {"asian": (0, 8), "london": (8, 16), "ny": (13, 21)}

LOOKBACKS = [60, 100, 150]
LOW_PCTL = 20
HIGH_PCTL = 80
REGIMES = ["low", "normal", "high"]

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


def label_regimes(df, lookback):
    ratios = df["ratio"].values
    regimes = [None] * len(ratios)
    for i in range(lookback, len(ratios)):
        window = ratios[i - lookback:i]
        lo, hi = np.percentile(window, [LOW_PCTL, HIGH_PCTL])
        regimes[i] = "low" if ratios[i] < lo else ("high" if ratios[i] > hi else "normal")
    df = df.copy()
    df["regime"] = regimes
    df["prior_regime"] = df["regime"].shift(1)
    return df.dropna(subset=["regime", "prior_regime"])


def class_freqs(labels):
    if len(labels) == 0:
        return {r: 1 / 3 for r in REGIMES}
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
    raw = daily_session_ratio(start_h, end_h)
    print(f"\n{'='*70}\nSession: {name}\n{'='*70}")
    for lookback in LOOKBACKS:
        df = label_regimes(raw, lookback)
        wins, total = 0, 0
        print(f"\n  --- lookback={lookback} days ---")
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
        print(f"  Summary for lookback={lookback}: beats majority in {wins}/{total} combos")