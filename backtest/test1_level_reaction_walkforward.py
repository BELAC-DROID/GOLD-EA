"""
Phase 3, Test 1, Metric B: Level-Reaction Walk-Forward Calibration (v2)

Rebuilt to use level_reaction_v2's price-tiering (via level_reaction_core.py)
instead of a flat $10 spacing - the original version of this script
predated the tiering fix and used the same fixed-dollar-spacing
assumption that broke level_reaction.py and the range-prediction model.

Stratifies by TIER (tier1_under_3000 / tier2_3000_and_above), not
major/minor level - level_reaction_v2's own findings showed major/minor
adds no real distinguishing value, so it's not worth carrying into the
walk-forward comparison either.

Three comparison points, same structure as before:
  naive (hard):       100%-confident guess on the pooled majority class
  pooled-soft:        train-period frequencies WITHOUT tier split
  model (stratified):  train-period frequencies, split by tier

model vs. pooled-soft is the comparison that matters - it isolates
whether tiering adds real predictive value.
"""

import sys
import duckdb
import numpy as np

sys.path.insert(0, r"C:\Users\opc\gold_ea\models")
from level_reaction_core import TIERS, build_classified_all_tiers

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

SPLITS = [
    ("2019-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("2019-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
    ("2019-01-01", "2024-12-31", "2025-01-01", None),
]

OUTCOMES = ["break", "reject", "consolidate"]
TIER_NAMES = [t["name"] for t in TIERS]
N_BOOTSTRAP = 2000
RNG = np.random.default_rng(42)


def fetch_split(con, start, end):
    where = f"day >= '{start}'" + (f" AND day <= '{end}'" if end else "")
    return con.execute(f"SELECT tier_name, outcome FROM classified_all WHERE {where}").fetchall()


def class_freqs(rows):
    if not rows:
        return {o: 1 / 3 for o in OUTCOMES}
    counts = {o: 0 for o in OUTCOMES}
    for o in rows:
        counts[o] += 1
    n = len(rows)
    return {o: counts[o] / n for o in OUTCOMES}


def brier(pred_probs, actual_outcome):
    return sum((pred_probs[o] - (1.0 if o == actual_outcome else 0.0)) ** 2 for o in OUTCOMES)


def bootstrap_ci(values, n=N_BOOTSTRAP):
    values = np.array(values)
    boots = [np.mean(RNG.choice(values, size=len(values), replace=True)) for _ in range(n)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return lo, hi


def run_split(con, train_start, train_end, test_start, test_end):
    train_rows = fetch_split(con, train_start, train_end)
    test_rows = fetch_split(con, test_start, test_end)
    if len(train_rows) < 30 or len(test_rows) < 30:
        return None

    train_by_tier = {t: [o for tier, o in train_rows if tier == t] for t in TIER_NAMES}
    train_pooled = [o for _, o in train_rows]

    model_freqs = {t: class_freqs(train_by_tier[t]) for t in TIER_NAMES}
    pooled_freqs = class_freqs(train_pooled)
    naive_majority_class = max(pooled_freqs, key=pooled_freqs.get)
    naive_probs = {o: (1.0 if o == naive_majority_class else 0.0) for o in OUTCOMES}

    model_scores, naive_scores, pooled_soft_scores = [], [], []
    for tier, actual in test_rows:
        model_scores.append(brier(model_freqs[tier], actual))
        naive_scores.append(brier(naive_probs, actual))
        pooled_soft_scores.append(brier(pooled_freqs, actual))

    model_mean, naive_mean, pooled_soft_mean = np.mean(model_scores), np.mean(naive_scores), np.mean(pooled_soft_scores)
    model_ci = bootstrap_ci(model_scores)

    return {
        "train_n": len(train_rows), "test_n": len(test_rows),
        "naive_majority_class": naive_majority_class,
        "model_brier": round(model_mean, 4), "model_brier_95ci": tuple(round(x, 4) for x in model_ci),
        "naive_brier": round(naive_mean, 4),
        "pooled_soft_brier": round(pooled_soft_mean, 4),
        "beats_naive": model_mean < naive_mean,
        "beats_pooled_soft": model_mean < pooled_soft_mean,
    }


if __name__ == "__main__":
    con = duckdb.connect(ANALYTICS_DB)
    print("Building tiered touch/outcome classification from minute_bars_ohlc...")
    build_classified_all_tiers(con)
    print("Done.\n")

    for i, (train_start, train_end, test_start, test_end) in enumerate(SPLITS, 1):
        test_label = test_end if test_end else "latest available"
        print(f"=== Split {i}: train {train_start}->{train_end}, test {test_start}->{test_label} ===")
        result = run_split(con, train_start, train_end, test_start, test_end)
        if result is None:
            print("  insufficient data for this split\n")
            continue
        flag = "BEATS naive" if result["beats_naive"] else "worse than naive"
        flag2 = "BEATS pooled-soft" if result["beats_pooled_soft"] else "does NOT beat pooled-soft"
        print(f"  train touches={result['train_n']:,}  test touches={result['test_n']:,}")
        print(f"  naive majority class (pooled train): {result['naive_majority_class']}")
        print(f"  model Brier={result['model_brier']} (95% CI {result['model_brier_95ci']})  vs  "
              f"naive Brier={result['naive_brier']}  -> {flag}")
        print(f"  model Brier={result['model_brier']}  vs  pooled-soft Brier={result['pooled_soft_brier']}  -> {flag2}")
        print()