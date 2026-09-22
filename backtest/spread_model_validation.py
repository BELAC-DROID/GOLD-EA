"""
Metric J - direct spread validation (the item flagged in spread_model.py's
own docstring as never done: "price-magnitude ratios as a proxy for
spread-widening ratios ... no one has directly measured Exness spread
behavior around a GDP or PCE release").

Uses ticks WHERE source='exness_live' (70.9M real ticks, ~2026-01-01 to
2026-09-18, confirmed demo-vs-live spread match on 2026-09-04 NFP -
see spread_check comparison). Imports SPIKE_TEMPLATE, FAMILY_SCALE_FACTOR,
RELEASE_FAMILY, EVENT_NAME_WHITELIST, EVENT_CURRENCIES, MIN_OFFSET,
MAX_OFFSET directly from spread_model.py - not duplicated - so this
validates the exact object the EA uses, not a re-typed copy.

METHOD
  For each whitelisted event (same-timestamp events grouped and assigned
  the max-scale family, exactly as spread_model.py's nearest_event_group
  does - so this validates what the live system actually decides, warts
  and all):
    baseline = median (ask-bid) in [-30, -3) minutes before the event,
               from this SAME day (controls for that day's liquidity,
               avoids needing/trusting normal_day_spread_profile.json)
    for each offset i in MIN_OFFSET..MAX_OFFSET (minutes from event):
        observed_mult(event, i) = mean(ask-bid) in [i, i+1) minutes / baseline
  Events are dropped if another whitelisted event group falls within 40
  minutes (avoids contaminating baseline or spike window with a second
  event), or if the event isn't on a weekday, or if tick coverage in the
  baseline/offset windows is too thin (< MIN_BASELINE_TICKS /
  MIN_OFFSET_TICKS).

  Per family, per offset: mean of observed_mult across events, with a
  cluster (event-level) bootstrap 95% CI - clustering at the event, not
  the tick, because ticks within one event are highly correlated.

TWO SEPARATE QUESTIONS, KEPT SEPARATE
  Q1 (does the base SHAPE generalize past the single Sept 4 event?):
     NFP family only, ALL NFP events found, raw SPIKE_TEMPLATE (scale=1.00)
     vs observed, every offset.
  Q2 (does the FAMILY SCALE FACTOR - built from Metric J's PRICE magnitude
      ratios - actually predict SPREAD widening?): every family, offset 0
      (the peak) specifically. Reports both:
        - whether the predicted multiplier falls inside the observed CI
        - the "implied scale factor" = (observed_mult_0 - 1) / (NFP's own
          raw mult_0 - 1), which is the scale factor spread data alone
          would suggest - compare directly to FAMILY_SCALE_FACTOR.

CAVEAT ON RELEASE_FAMILY DEFAULT: spread_model.py's own code falls back
to family "NFP" (scale 1.00) for any event name it doesn't recognize
(RELEASE_FAMILY.get(n, "NFP")). This script mirrors that fallback so it
tests actual system behavior, but flags if it ever triggers - a silent
mis-scale in production would look the same way.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\spread_model_validation.py
Output: console tables + spread_model_validation_results.csv

PERFORMANCE NOTE (2026-09-21): the `ticks` table (424M rows) has no index on
(source, timestamp_utc_ms). The first version of this script queried it once
per event (56 queries for 28 events = 56 full-table scans) and hung for
hours. Fixed: the whole source slice (~71M rows for exness_live) is now
pulled ONCE into memory as sorted numpy arrays, and every event's baseline/
offset windows are located with np.searchsorted (microseconds) instead of a
SQL query. Expect one multi-minute load, then a fast finish.
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, r"C:\Users\opc\gold_ea\models")
from spread_model import (SPIKE_TEMPLATE, FAMILY_SCALE_FACTOR, RELEASE_FAMILY,
                           EVENT_NAME_WHITELIST, EVENT_CURRENCIES, MIN_OFFSET, MAX_OFFSET)

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
SOURCE = "exness_live"
BASELINE_START_MIN, BASELINE_END_MIN = -30, -3
MIN_SPACING_MIN = 40
MIN_BASELINE_TICKS = 20
MIN_OFFSET_TICKS = 3
N_BOOT = 1000
SEED = 31


def get_coverage(con):
    r = con.execute("SELECT min(timestamp_utc_ms), max(timestamp_utc_ms) FROM ticks WHERE source=?", [SOURCE]).fetchone()
    return r[0], r[1]


def get_event_groups(con, lo_ms, hi_ms):
    """One row per distinct whitelisted-event timestamp in [lo, hi], with the
    family spread_model.py's own nearest_event_group() would report (max
    scale factor among event names sharing that timestamp)."""
    name_ph = ",".join("?" for _ in EVENT_NAME_WHITELIST)
    curr_ph = ",".join("?" for _ in EVENT_CURRENCIES)
    rows = con.execute(f"""
        SELECT timestamp_utc_ms, list(event_name) AS names
        FROM calendar_events
        WHERE event_name IN ({name_ph}) AND currency IN ({curr_ph})
          AND timestamp_utc_ms BETWEEN ? AND ?
        GROUP BY timestamp_utc_ms ORDER BY timestamp_utc_ms
    """, (*EVENT_NAME_WHITELIST, *EVENT_CURRENCIES, lo_ms, hi_ms)).fetchdf()
    if rows.empty:
        return rows
    fam_fallback = []
    families, scales = [], []
    for names in rows["names"]:
        fams = [RELEASE_FAMILY.get(n, "NFP") for n in names]
        fam_fallback.append(any(n not in RELEASE_FAMILY for n in names))
        fam = max(fams, key=lambda f: FAMILY_SCALE_FACTOR.get(f, 1.0))
        families.append(fam)
        scales.append(FAMILY_SCALE_FACTOR.get(fam, 1.0))
    rows["family"] = families
    rows["scale"] = scales
    rows["fallback_used"] = fam_fallback
    ts = rows["timestamp_utc_ms"].values
    weekday_ok = pd.to_datetime(ts, unit="ms", utc=True).dayofweek < 5
    spacing_ok = np.ones(len(ts), dtype=bool)
    if len(ts) > 1:
        gaps_min = np.diff(ts) / 60000.0
        spacing_ok[:-1] &= gaps_min >= MIN_SPACING_MIN
        spacing_ok[1:] &= gaps_min >= MIN_SPACING_MIN
    rows["kept"] = weekday_ok & spacing_ok
    return rows


def load_source_ticks(con, source=SOURCE):
    """Pull the whole source slice ONCE, sorted, as numpy arrays. Avoids issuing
    one SQL query per event: the ticks table has no index on (source,
    timestamp_utc_ms), so N per-event queries means N full-table scans - this
    turned a ~3-hour hang (56 scans of 424M rows) into a single scan."""
    print(f"loading all '{source}' ticks into memory (one full scan - this is the slow part, ~a few minutes)...")
    import time
    t0 = time.time()
    df = con.execute(
        "SELECT timestamp_utc_ms, bid, ask FROM ticks WHERE source = ? ORDER BY timestamp_utc_ms", [source]
    ).fetchdf()
    ts = df["timestamp_utc_ms"].values.astype(np.int64)
    spread = (df["ask"].values - df["bid"].values).astype(np.float64)
    print(f"loaded {len(ts):,} ticks in {time.time() - t0:.0f}s "
          f"(~{ts.nbytes / 1e6 + spread.nbytes / 1e6:.0f} MB in memory)")
    return ts, spread


def event_multipliers(ts, spread, ts_ms):
    """Returns (baseline, {offset: mean_mult}) or None if too little data.
    ts, spread: full sorted arrays from load_source_ticks(). Uses
    np.searchsorted (O(log n)) instead of a SQL query per event."""
    lo = ts_ms + BASELINE_START_MIN * 60000
    hi = ts_ms + BASELINE_END_MIN * 60000
    i0, i1 = np.searchsorted(ts, [lo, hi])
    if i1 - i0 < MIN_BASELINE_TICKS:
        return None
    baseline = float(np.median(spread[i0:i1]))
    if baseline <= 0:
        return None

    win_lo, win_hi = ts_ms + MIN_OFFSET * 60000, ts_ms + (MAX_OFFSET + 1) * 60000
    j0, j1 = np.searchsorted(ts, [win_lo, win_hi])
    if j1 <= j0:
        return None
    win_ts, win_spread = ts[j0:j1], spread[j0:j1]
    offsets = (win_ts - ts_ms) // 60000

    mults = {}
    for off in range(MIN_OFFSET, MAX_OFFSET + 1):
        s = win_spread[offsets == off]
        if len(s) < MIN_OFFSET_TICKS:
            continue
        mults[off] = float(s.mean()) / baseline
    return baseline, mults


def cluster_bootstrap_mean(values_by_event, n_boot=N_BOOT, seed=SEED):
    """values_by_event: 1D array, one value per event (already offset-specific)."""
    v = np.asarray(values_by_event, dtype=float)
    n = len(v)
    if n == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    boots = v[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(v.mean()), float(lo), float(hi)


def main(con=None):
    if con is None:
        con = duckdb.connect(DB_PATH, read_only=True)
    lo_ms, hi_ms = get_coverage(con)
    print(f"{SOURCE} coverage: {pd.to_datetime(lo_ms, unit='ms', utc=True)} -> {pd.to_datetime(hi_ms, unit='ms', utc=True)}")

    groups = get_event_groups(con, lo_ms, hi_ms)
    if groups.empty:
        print("No whitelisted events found in this coverage window.")
        return
    print(f"whitelisted event timestamps in window: {len(groups)}  "
          f"(kept after weekday+spacing filter: {int(groups['kept'].sum())})")
    if groups["fallback_used"].any():
        print(f"WARNING: {int(groups['fallback_used'].sum())} event(s) had a name not in RELEASE_FAMILY "
              f"and fell back to family='NFP' (scale=1.00) - check these event names.")

    per_event = []   # family, offset, mult
    baselines = []
    ts_arr, spread_arr = load_source_ticks(con)
    for _, row in groups[groups["kept"]].iterrows():
        res = event_multipliers(ts_arr, spread_arr, int(row["timestamp_utc_ms"]))
        if res is None:
            continue
        baseline, mults = res
        baselines.append({"family": row["family"], "ts": row["timestamp_utc_ms"], "baseline": baseline})
        for off, m in mults.items():
            per_event.append({"family": row["family"], "ts": row["timestamp_utc_ms"], "offset": off, "mult": m})
    if not per_event:
        print("No events had usable tick coverage.")
        return
    pe = pd.DataFrame(per_event)
    bl = pd.DataFrame(baselines)
    print("\nusable events per family:")
    print(bl.groupby("family")["ts"].nunique().to_string())
    print("\nmedian local baseline spread per family (price units):")
    print(bl.groupby("family")["baseline"].median().round(4).to_string())

    rows_out = []

    # ---------------- Q1: NFP shape, all events vs the single-event template ----------------
    print("\n" + "=" * 90)
    print("Q1 - does SPIKE_TEMPLATE's shape (built from ONE Sept-4 event) generalize across all NFP events?")
    print("=" * 90)
    nfp = pe[pe["family"] == "NFP"]
    n_nfp = nfp["ts"].nunique()
    print(f"NFP events used: {n_nfp}")
    print(f"{'offset':>6s} {'template':>9s} {'observed':>9s} {'95% CI':>17s} {'n_ev':>5s}  in_CI")
    for off in range(MIN_OFFSET, MAX_OFFSET + 1):
        vals = nfp.loc[nfp["offset"] == off, "mult"].values
        tmpl = SPIKE_TEMPLATE[off][0]
        mean, lo, hi = cluster_bootstrap_mean(vals)
        in_ci = (lo <= tmpl <= hi) if not np.isnan(lo) else None
        print(f"{off:6d} {tmpl:9.3f} {mean:9.3f} [{lo:6.3f},{hi:6.3f}] {len(vals):5d}  {in_ci}")
        rows_out.append({"question": "Q1_shape", "family": "NFP", "offset": off, "template": tmpl,
                         "observed_mean": mean, "ci_lo": lo, "ci_hi": hi, "n_events": len(vals), "in_ci": in_ci})

    # ---------------- Q2: family scale factor at the peak offset ----------------
    print("\n" + "=" * 90)
    print("Q2 - does FAMILY_SCALE_FACTOR (derived from Metric J PRICE-magnitude ratios) predict")
    print("     observed SPREAD widening at the peak offset (0)?")
    print("=" * 90)
    nfp_peak_tmpl = SPIKE_TEMPLATE[0][0]
    print(f"{'family':>6s} {'declared_scale':>14s} {'predicted':>10s} {'observed':>9s} {'95% CI':>17s} "
          f"{'n_ev':>5s} {'in_CI':>6s} {'implied_scale':>13s}")
    for fam in sorted(pe["family"].unique()):
        vals = pe.loc[(pe["family"] == fam) & (pe["offset"] == 0), "mult"].values
        n_ev = pe.loc[(pe["family"] == fam), "ts"].nunique()
        declared = FAMILY_SCALE_FACTOR.get(fam, 1.0)
        predicted = 1 + declared * (nfp_peak_tmpl - 1)
        mean, lo, hi = cluster_bootstrap_mean(vals)
        in_ci = (lo <= predicted <= hi) if not np.isnan(lo) else None
        implied = (mean - 1) / (nfp_peak_tmpl - 1) if not np.isnan(mean) else np.nan
        print(f"{fam:>6s} {declared:14.2f} {predicted:10.3f} {mean:9.3f} [{lo:6.3f},{hi:6.3f}] "
              f"{n_ev:5d} {str(in_ci):>6s} {implied:13.2f}")
        rows_out.append({"question": "Q2_scale", "family": fam, "offset": 0, "declared_scale": declared,
                         "predicted": predicted, "observed_mean": mean, "ci_lo": lo, "ci_hi": hi,
                         "n_events": len(vals), "in_ci": in_ci, "implied_scale": implied})

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spread_model_validation_results.csv")
    pd.DataFrame(rows_out).to_csv(out, index=False)
    print(f"\nSaved: {out}")
    print("\nHow to read Q2: 'in_CI'=True means the price-magnitude-derived scale factor is consistent with")
    print("measured spread widening for that family. implied_scale is what the spread data alone would")
    print("suggest for FAMILY_SCALE_FACTOR - compare it directly to declared_scale. Families with few events")
    print("(GDP is quarterly - expect ~2-3 in an 8-month window) will have wide CIs; read those cautiously.")


if __name__ == "__main__":
    main()