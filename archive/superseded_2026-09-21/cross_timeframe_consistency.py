"""
Phase 3, Test 1, Metric I: Cross-Timeframe Consistency (extended to all 4 available timeframes)

D1 lookback=100 matches Metric C's own daily lookback exactly, for a
direct comparison point. Stride/lookback ratios kept at ~67% (matching
Metric D's validated choice) across all four timeframes, scaled by
each timeframe's approximate bars/day.

NOTE: D1 only has ~1,860 total bars - after a 100-bar lookback burn-in
and further train/test splitting per combo, some combos may end up
with a thin sample. Watch n_test for D1 specifically before trusting
any "does not beat majority" result there - it could be sample size,
not absence of signal.
"""

import duckdb
import numpy as np
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
REGIMES = ["low", "normal", "high"]

TIMEFRAMES = {
    "h1": {"table": "bars_h1", "lookback": 2400, "stride": 800},
    "h4": {"table": "bars_h4", "lookback": 600, "stride": 200},
    "m30": {"table": "bars_m30", "lookback": 4800, "stride": 1600},
    "d1": {"table": "bars_d1", "lookback": 100, "stride": 33},
}

con = duckdb.connect(ANALYTICS_DB)


def bar_data(table):
    return con.execute(f"""
        SELECT bar_ts AS day, high, low,
               LAG(close) OVER (ORDER BY bar_ts) AS prior_close
        FROM {table}
        WHERE close IS NOT NULL
        ORDER BY bar_ts
    """).fetchdf().dropna(subset=["prior_close"])


def label(df, lookback, stride):
    ratios = ((df["high"] - df["low"]) / df["prior_close"]).values
    n = len(ratios)
    regimes = [None] * n
    for i in range(lookback, n):
        window = ratios[i - lookback:i]
        lo, hi = np.percentile(window, [20, 80])
        regimes[i] = "low" if ratios[i] < lo else ("high" if ratios[i] > hi else "normal")
    df = df.copy()
    df["regime"] = regimes
    df["prior_regime"] = df["regime"].shift(stride)
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


for tf_name, cfg in TIMEFRAMES.items():
    print(f"\n{'='*70}\nTimeframe: {tf_name.upper()} (lookback={cfg['lookback']}, stride={cfg['stride']})\n{'='*70}")
    raw = bar_data(cfg["table"])
    print(f"  total bars available: {len(raw):,}")
    df = label(raw, cfg["lookback"], cfg["stride"])
    if len(df) < 50:
        print(f"  WARNING: only {len(df)} usable observations after lookback/stride burn-in - too thin, skipping")
        continue

    unchanged_rate = np.mean(df["prior_regime"].values == df["regime"].values)
    base_unchanged = sum(v ** 2 for v in class_freqs(df["regime"].tolist()).values())
    print(f"  Stickiness check: {unchanged_rate:.1%} unchanged vs {base_unchanged:.1%} chance baseline "
          f"({'OK' if unchanged_rate < base_unchanged + 0.20 else 'WARNING - check before trusting'})")
    print(f"  regime distribution: {class_freqs(df['regime'].tolist())}")

    wins, total = 0, 0
    for combo in COMBOS:
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
            print(f"    {combo['name']:25s}  no valid folds")
            continue
        model_b, maj_b = np.mean(model_scores), np.mean(majority_scores)
        beats = model_b < maj_b
        wins += int(beats)
        total += 1
        flag = "BEATS majority" if beats else "does not beat majority"
        print(f"    {combo['name']:25s}  n_test={len(model_scores):6d}  model={model_b:.4f}  "
              f"majority={maj_b:.4f}  -> {flag}")
    print(f"  Summary ({tf_name}): beats majority in {wins}/{total} combos")