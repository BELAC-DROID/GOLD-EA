"""
2026 holdout, step 2b: Metrics C and H, single train(2019-2025)/test(2026)
split, following the same design as holdout_2026_evaluate.py (A and I).

UNLIKE METRIC A: C and H's core mechanics (rolling regime labels in C,
rolling percentile flags in H) are already adaptive - they don't need a
separate "fit on train" step the way A's flawed static training-mean model
did. The holdout question for these two is simpler: extend the SAME rolling
calculation across the 2019-2025 -> 2026 boundary (so 2026's windows are
properly seeded with real history), then score purely on the 2026 side.
For C, the majority-baseline class frequencies ARE fit on train only (to
avoid leaking 2026's own class balance into its own baseline) - same
principle as the original walk-forward folds and as Metric I's holdout.

Reuses volatility_regime_classification_v3.py (Metric C's label_regimes),
anomaly_flagging_v2.py (Metric H's trailing_above/build_flag_frame/event
lookup), range_prediction_v3_baselines.py (session helpers), and
score_transition from holdout_2026_evaluate.py (Metric I's holdout scorer -
same 3-class Brier-vs-majority logic applies unchanged to C's low/normal/
high labels).

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\holdout_2026_ch.py
Output: console tables + holdout_2026_ch_results.csv
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import range_prediction_v3_baselines as R
import volatility_regime_classification_v3 as V
import anomaly_flagging_v2 as HF   # "HF" = Metric H File, avoids clashing with Metric-C's "H" naming elsewhere
from holdout_2026_evaluate import score_transition
from cross_timeframe_consistency_v2 import block_boot_ci

ORIG_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
HOLDOUT_DB = r"C:\Users\opc\gold_ea\data\analytics_2026_holdout.duckdb"
SPLIT_DATE = "2026-01-01"
REGIME_CODE = {"low": 0, "normal": 1, "high": 2}


# ============================================================ Metric C ====
def metric_c_holdout(con_orig, con_hold, rows_out):
    print("\n" + "=" * 90)
    print("METRIC C HOLDOUT - session regime persistence, trained on 2019-2025, tested on 2026")
    print("=" * 90)
    prior_o, prior_h = R.prior_close_table(con_orig), R.prior_close_table(con_hold)

    jobs = [("asian", "fixed_utc", R.FIXED_SESSIONS["asian"], None)]
    for name in ["london", "ny"]:
        jobs.append((name, "fixed_utc", R.FIXED_SESSIONS[name], None))
        jobs.append((name, "dst_aware", None, R.DST_SESSIONS[name]))

    for name, mode, fixed_args, dst_args in jobs:
        if fixed_args:
            ranges_o = R.session_ranges_fixed(con_orig, *fixed_args)
            ranges_h = R.session_ranges_fixed(con_hold, *fixed_args)
        else:
            ranges_o = R.session_ranges_dst(con_orig, *dst_args)
            ranges_h = R.session_ranges_dst(con_hold, *dst_args)
        raw = pd.concat([ranges_o.merge(prior_o, on="day", how="inner"),
                         ranges_h.merge(prior_h, on="day", how="inner")], ignore_index=True)
        raw = raw.sort_values("day").reset_index(drop=True)
        raw["ratio"] = raw["day_range"] / raw["prior_close"]

        print(f"\n{name.upper()} | {mode}")
        for lookback in [60, 100, 150]:
            labeled = V.label_regimes(raw[["day", "ratio"]], lookback)
            cur = labeled["regime"].map(REGIME_CODE).values
            pri = labeled["prior_regime"].map(REGIME_CODE).values
            day = labeled["day"].values
            tr_mask, te_mask = day < np.datetime64(SPLIT_DATE, "ns"), day >= np.datetime64(SPLIT_DATE, "ns")
            r = score_transition(cur[tr_mask], pri[tr_mask], cur[te_mask], pri[te_mask])
            if r is None:
                print(f"  lookback={lookback:3d}: insufficient data, skipping")
                continue
            block_len = 20
            diff_arr = r["major_brier_arr"] - r["model_brier_arr"]
            obs, lo, hi = block_boot_ci(diff_arr, block_len)
            gain_lo, gain_hi = lo / r["brier_major"] * 100, hi / r["brier_major"] * 100
            sig = "significant" if lo > 0 else ("significantly WORSE" if hi < 0 else "not significant")
            print(f"  lookback={lookback:3d}  n_train={r['n_train']:4d} n_test={r['n_test']:3d}  "
                  f"gain={r['gain_pct']:+.2f}%  95% CI [{gain_lo:+.2f}%,{gain_hi:+.2f}%]  -> {sig}")
            rows_out.append({"metric": "C", "session": name, "mode": mode, "lookback": lookback,
                             "n_train": r["n_train"], "n_test": r["n_test"], "gain_pct": r["gain_pct"],
                             "gain_ci_lo": gain_lo, "gain_ci_hi": gain_hi, "sig": sig})


# ============================================================ Metric H ====
def block_bootstrap_precision(f, a, block_len=10, n_boot=1000, seed=51):
    n = len(f)
    L = max(1, min(block_len, n // 5 if n >= 5 else 1))
    nb = int(np.ceil(n / L))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(n_boot, nb))
    idx = ((starts[:, :, None] + np.arange(L)[None, None, :]) % n).reshape(n_boot, -1)[:, :n]
    ff, aa = f[idx], a[idx]
    nf = ff.sum(axis=1)
    ok = nf > 0
    d = (np.where(ok, (ff & aa).sum(axis=1) / np.maximum(nf, 1), np.nan) - aa.mean(axis=1))[ok]
    return np.nanpercentile(d, [2.5, 97.5])


def score_flag_2026(df, flag_col, truth_col, split=SPLIT_DATE):
    d = df.dropna(subset=[flag_col, truth_col])
    test = d[d["day"] >= split]
    f, a = test[flag_col].values.astype(bool), test[truth_col].values.astype(bool)
    n_flagged = int(f.sum())
    if n_flagged < 10:
        return {"n_days": len(f), "n_flagged": n_flagged, "code": "."}
    precision, base = a[f].mean(), a.mean()
    lo, hi = block_bootstrap_precision(f, a)
    diff = precision - base
    code = "significant" if lo > 0 else ("significantly WORSE" if hi < 0 else "not significant")
    return {"n_days": len(f), "n_flagged": n_flagged, "precision": precision, "base_rate": base,
            "lift": precision / base if base > 0 else float("nan"), "diff": diff,
            "ci_lo": lo, "ci_hi": hi, "code": code}


def metric_h_holdout(con_orig, con_hold, rows_out):
    print("\n" + "=" * 90)
    print("METRIC H HOLDOUT - anomaly-flagging precision, trained on 2019-2025, tested on 2026")
    print("=" * 90)
    prior_o, prior_h = R.prior_close_table(con_orig), R.prior_close_table(con_hold)

    jobs = [("asian", "fixed_utc", HF.session_open_rest_full(con_orig, 0, 8),
             HF.session_open_rest_full(con_hold, 0, 8))]
    for name in ["london", "ny"]:
        fs, fe = R.FIXED_SESSIONS[name]
        jobs.append((name, "fixed_utc", HF.session_open_rest_full(con_orig, fs, fe),
                     HF.session_open_rest_full(con_hold, fs, fe)))
        ls, le, tz = R.DST_SESSIONS[name]
        jobs.append((name, "dst_aware", HF.session_open_rest_full(con_orig, ls, le, tz),
                     HF.session_open_rest_full(con_hold, ls, le, tz)))

    HF.open_calendar(con_orig)
    names, currs = HF.load_event_config()

    for name, mode, raw_o, raw_h in jobs:
        raw = pd.concat([raw_o, raw_h], ignore_index=True).sort_values("day").reset_index(drop=True)
        prior = pd.concat([prior_o, prior_h], ignore_index=True).drop_duplicates("day")
        df = HF.build_flag_frame(raw, prior)

        print(f"\n{name.upper()} | {mode} | sessions={len(df)}")
        for truth in ["full", "rest"]:
            r = score_flag_2026(df, "flag_open", f"high_{truth}")
            if r.get("code") == ".":
                print(f"  open-flag vs {truth}: too few 2026 flagged days ({r['n_flagged']})")
                continue
            print(f"  open-flag vs {truth}: precision={r['precision']:.3f} base={r['base_rate']:.3f} "
                  f"lift={r['lift']:.2f}x  95% CI on diff [{r['ci_lo']:+.3f},{r['ci_hi']:+.3f}]  -> {r['code']}")
            rows_out.append({"metric": "H", "part": "opening_range", "session": name, "mode": mode,
                             "truth": truth, **r})

        if name == "asian":
            s, e, tz = 0, 8, None
        elif mode == "fixed_utc":
            (s, e), tz = R.FIXED_SESSIONS[name], None
        else:
            s, e, tz = R.DST_SESSIONS[name]
        days = HF.event_days(con_orig, names, currs, s, e, tz)
        df["flag_cal"] = df["day"].isin(days).astype(float)
        r = score_flag_2026(df, "flag_cal", "high_full")
        if r.get("code") == ".":
            print(f"  calendar-flag: too few 2026 flagged days ({r['n_flagged']})")
        else:
            print(f"  calendar-flag: precision={r['precision']:.3f} base={r['base_rate']:.3f} "
                  f"lift={r['lift']:.2f}x  95% CI on diff [{r['ci_lo']:+.3f},{r['ci_hi']:+.3f}]  -> {r['code']}")
            rows_out.append({"metric": "H", "part": "calendar", "session": name, "mode": mode, **r})


def main(con_orig=None, con_hold=None):
    if con_orig is None:
        con_orig = duckdb.connect(ORIG_DB, read_only=True)
    if con_hold is None:
        con_hold = duckdb.connect(HOLDOUT_DB, read_only=True)
    for c in (con_orig, con_hold):
        c.execute("SET TimeZone='UTC'")

    rows_out = []
    metric_c_holdout(con_orig, con_hold, rows_out)
    metric_h_holdout(con_orig, con_hold, rows_out)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdout_2026_ch_results.csv")
    pd.DataFrame(rows_out).to_csv(out, index=False)
    print(f"\nSaved: {out}")
    print("\nNote: calendar-flag event lookup uses gold_data.db's calendar_events (ATTACHed via con_orig) -")
    print("shared across both periods, not source-filtered, so 2026 events are included automatically.")


if __name__ == "__main__":
    main()