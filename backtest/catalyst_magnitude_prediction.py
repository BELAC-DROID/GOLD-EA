"""
Phase 3, Test 1, Metric J: Catalyst Magnitude Prediction (v3)
(also closes the Phase 1 debt: spread_model.py's SPIKE_TEMPLATE was
calibrated on exactly one NFP event and never validated against others)

Root cause of v1/v2's inflated counts, found via staged diagnostic:
calendar_events genuinely has multiple event_names sharing one exact
release timestamp (CPI/PCE/FOMC families each publish several named
sub-metrics simultaneously) - 979 raw event rows, only 494 distinct
timestamps. v1 didn't dedup at all (2,595 rows). v2 deduped AFTER the
price joins, by which point pre_price/post_price already each carried
the duplicate timestamps, so joining them combinatorially multiplied
each duplicate group (2 dupes x 2 dupes = 4 rows) instead of cleanly
matching - still wrong (426, not 494). Correct fix: dedup the events
table to one row per timestamp BEFORE any price join, so pre_price and
post_price are each built from a clean, duplicate-free set of release
moments from the start.

NOTE: spread_model.py's reported 979 is NOT the right validation
target for a deduplicated release-moment count - it's the raw,
intentionally-undeduplicated count (fine for its own nearest-event
lookup use case). The correct target is 494 distinct timestamps.
"""

import sys
import duckdb
import numpy as np
from scipy import stats

sys.path.insert(0, r"C:\Users\opc\gold_ea\models")
from spread_model import EVENT_NAME_WHITELIST, EVENT_CURRENCIES

from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
PRE_EVENT_MINUTES = 2
POST_EVENT_MINUTES = 8

RELEASE_FAMILY = {
    "CPI": "CPI_release", "CPI y/y": "CPI_release", "CPI m/m": "CPI_release",
    "Core CPI m/m": "CPI_release", "Core CPI n.s.a. m/m": "CPI_release",
    "Core PCE Price Index m/m": "PCE_release", "Core PCE Price Index y/y": "PCE_release",
    "FOMC Statement": "FOMC_release", "FOMC Press Conference": "FOMC_release",
    "Nonfarm Payrolls": "NFP_release", "GDP q/q": "GDP_release",
}

con = duckdb.connect(ANALYTICS_DB)
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")

name_ph = ",".join("?" for _ in EVENT_NAME_WHITELIST)
curr_ph = ",".join("?" for _ in EVENT_CURRENCIES)
params = (*EVENT_NAME_WHITELIST, *EVENT_CURRENCIES)

# Dedup FIRST: one row per distinct timestamp, before any price join.
# ANY_VALUE picks one event_name per timestamp group arbitrarily - fine,
# since we immediately map it to its release_family anyway, and every
# event_name sharing a timestamp maps to the same family by construction.
events_dedup_ts = con.execute(f"""
    SELECT any_value(event_name) AS event_name, timestamp_utc_ms,
           date_trunc('day', to_timestamp(timestamp_utc_ms/1000.0)) AS event_day
    FROM gold.calendar_events
    WHERE event_name IN ({name_ph}) AND currency IN ({curr_ph})
    GROUP BY timestamp_utc_ms
""", params).fetchdf()

print(f"Distinct release timestamps (the correct base count): {len(events_dedup_ts)}")
print(f"(this is the number to trust - NOT spread_model.py's 979, which is intentionally undeduplicated)\n")

events_dedup_ts["release_family"] = events_dedup_ts["event_name"].map(RELEASE_FAMILY)

con.execute("CREATE OR REPLACE TEMP TABLE events_clean AS SELECT * FROM events_dedup_ts")

events_with_moves = con.execute(f"""
    WITH pre_price AS (
        SELECT e.timestamp_utc_ms, e.event_name, e.event_day, e.release_family,
               m.close AS pre_close
        FROM events_clean e
        JOIN minute_bars_ohlc m
          ON m.minute_ts = date_trunc('minute', to_timestamp(e.timestamp_utc_ms/1000.0))
             - INTERVAL '{PRE_EVENT_MINUTES} minutes'
    ),
    post_price AS (
        SELECT e.timestamp_utc_ms, m.close AS post_close
        FROM events_clean e
        JOIN minute_bars_ohlc m
          ON m.minute_ts = date_trunc('minute', to_timestamp(e.timestamp_utc_ms/1000.0))
             + INTERVAL '{POST_EVENT_MINUTES} minutes'
    )
    SELECT p.event_name, p.event_day AS day, p.release_family, p.timestamp_utc_ms,
           ABS(po.post_close - p.pre_close) / p.pre_close AS magnitude
    FROM pre_price p
    JOIN post_price po ON po.timestamp_utc_ms = p.timestamp_utc_ms
    ORDER BY p.timestamp_utc_ms
""").fetchdf()

print(f"Final deduplicated events with valid before/after price data: {len(events_with_moves)}")
print(f"(should be <= {len(events_dedup_ts)}, reduced only by missing-bar dropouts, no fan-out)\n")

# ---------- Part 1: does NFP's magnitude distribution match the others? ----------
print("="*70)
print("Part 1: Per-release-family magnitude distribution (closes Phase 1 debt)")
print("="*70)
by_family = events_with_moves.groupby("release_family")["magnitude"]
summary = by_family.agg(["count", "mean", "median", "std"]).sort_values("mean", ascending=False)
print(summary.to_string())

nfp_moves = events_with_moves[events_with_moves["release_family"] == "NFP_release"]["magnitude"]
other_moves = events_with_moves[events_with_moves["release_family"] != "NFP_release"]["magnitude"]
if len(nfp_moves) > 5 and len(other_moves) > 5:
    t_stat, p_val = stats.ttest_ind(nfp_moves, other_moves, equal_var=False)
    print(f"\nNFP mean magnitude: {nfp_moves.mean():.5f}  (n={len(nfp_moves)})")
    print(f"All-other-families mean magnitude: {other_moves.mean():.5f}  (n={len(other_moves)})")
    print(f"Welch's t-test p-value: {p_val:.4f}  "
          f"({'NFP is significantly different - one-shape-fits-all assumption questionable' if p_val < 0.05 else 'no significant difference - one-shape-fits-all is a reasonable approximation'})")

# ---------- Part 2: walk-forward - per-family average vs pooled naive ----------
print(f"\n{'='*70}")
print("Part 2: Walk-forward magnitude prediction (per-family vs pooled naive)")
print("="*70)

for combo in COMBOS:
    splits = generate_splits(combo)
    model_errors, naive_errors = [], []
    for s in splits:
        train = events_with_moves[(events_with_moves["day"] >= s["train_start"]) & (events_with_moves["day"] <= s["train_end"])]
        test = events_with_moves[(events_with_moves["day"] >= s["test_start"]) & (events_with_moves["day"] <= s["test_end"])]
        if len(train) < 20 or len(test) < 5:
            continue
        pooled_naive_pred = train["magnitude"].mean()
        per_family_pred = train.groupby("release_family")["magnitude"].mean().to_dict()
        for _, row in test.iterrows():
            model_pred = per_family_pred.get(row["release_family"], pooled_naive_pred)
            model_errors.append(abs(row["magnitude"] - model_pred))
            naive_errors.append(abs(row["magnitude"] - pooled_naive_pred))
    if not model_errors:
        print(f"  {combo['name']:25s}  no valid folds")
        continue
    model_mae, naive_mae = np.mean(model_errors), np.mean(naive_errors)
    flag = "BEATS pooled naive" if model_mae < naive_mae else "does NOT beat pooled naive"
    print(f"  {combo['name']:25s}  n={len(model_errors):4d}  model_MAE={model_mae:.5f}  "
          f"naive_MAE={naive_mae:.5f}  -> {flag}")