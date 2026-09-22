"""
Applies the pre-committed window matrix to the tiered level-reaction
model. Reuses level_reaction_core.py's classification - only the split
generation changes. Compares model (tier-stratified) vs pooled-soft
(no tier split), per combo, pooling all folds.
"""

import sys
import duckdb
import numpy as np

sys.path.insert(0, r"C:\Users\opc\gold_ea\models")
from level_reaction_core import TIERS, build_classified_all_tiers
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
OUTCOMES = ["break", "reject", "consolidate"]
TIER_NAMES = [t["name"] for t in TIERS]

con = duckdb.connect(ANALYTICS_DB)
print("Building tiered touch/outcome classification...")
build_classified_all_tiers(con)
print("Done.\n")


def fetch(start, end):
    return con.execute(f"""
        SELECT tier_name, outcome FROM classified_all
        WHERE day >= '{start}' AND day <= '{end}'
    """).fetchall()


def class_freqs(rows):
    if not rows:
        return {o: 1 / 3 for o in OUTCOMES}
    counts = {o: 0 for o in OUTCOMES}
    for o in rows:
        counts[o] += 1
    n = len(rows)
    return {o: counts[o] / n for o in OUTCOMES}


def brier(pred, actual):
    return sum((pred[o] - (1.0 if o == actual else 0.0)) ** 2 for o in OUTCOMES)


for combo in COMBOS:
    splits = generate_splits(combo)
    model_scores, pooled_soft_scores = [], []
    total_train, total_test = 0, 0
    for s in splits:
        train_rows = fetch(s["train_start"], s["train_end"])
        test_rows = fetch(s["test_start"], s["test_end"])
        if len(train_rows) < 30 or len(test_rows) < 10:
            continue
        train_by_tier = {t: [o for tier, o in train_rows if tier == t] for t in TIER_NAMES}
        model_freqs = {t: class_freqs(train_by_tier[t]) for t in TIER_NAMES}
        pooled_freqs = class_freqs([o for _, o in train_rows])
        for tier, actual in test_rows:
            model_scores.append(brier(model_freqs[tier], actual))
            pooled_soft_scores.append(brier(pooled_freqs, actual))
        total_train += len(train_rows)
        total_test += len(test_rows)
    if not model_scores:
        print(f"{combo['name']:25s}  no valid folds")
        continue
    model_mean, pooled_mean = np.mean(model_scores), np.mean(pooled_soft_scores)
    flag = "BEATS pooled-soft" if model_mean < pooled_mean else "does NOT beat pooled-soft"
    print(f"{combo['name']:25s}  n_folds={len(splits):2d}  pooled_test_touches={len(model_scores):5d}  "
          f"model_Brier={model_mean:.4f}  pooled_soft_Brier={pooled_mean:.4f}  -> {flag}")