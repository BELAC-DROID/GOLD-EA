"""
2026 holdout, step 2a: Metrics A and I evaluated as a genuine single
train/test split - train on ALL of 2019-2025 (as already established in
Test 1), test purely on 2026 (analytics_2026_holdout.duckdb, built by
build_2026_holdout_bars.py).

WHY NOT JUST RUN THE EXISTING v3 SCRIPTS AGAINST THE NEW FILE: their
6-combo walk-forward matrix (walk_forward_matrix.py) is hardcoded to a
2019-2026 date range and needs 2+ years of history before its first test
window - pointed at a 2026-only database, every combo would report "no
valid folds". The right question for a holdout is also different in kind:
not "does the model hold up across many re-splits of a short window" but
"does the ALREADY-ESTABLISHED model, fit once on everything we had before,
hold up on data it has truly never seen". This script does that: it pulls
the SAME derived series (session ranges, time-of-day-relative regimes)
from BOTH the original analytics.duckdb (pre-2026) and the new holdout
file (2026), concatenates them in time order so rolling windows are
properly seeded going into 2026, then trains only on the pre-2026 side and
scores only on the 2026 side.

Reuses range_prediction_v3_baselines.py and cross_timeframe_consistency_v2.py
directly (session helpers, the deseasonalized-label builder) rather than
reimplementing them - same definitions, not a re-typed copy.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\holdout_2026_evaluate.py
Output: console tables + holdout_2026_results.csv
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import range_prediction_v3_baselines as R
import cross_timeframe_consistency_v2 as I

ORIG_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
HOLDOUT_DB = r"C:\Users\opc\gold_ea\data\analytics_2026_holdout.duckdb"
SPLIT_DATE = "2026-01-01"


# ============================================================ Metric A ====
def metric_a_holdout(con_orig, con_hold, rows_out):
    print("\n" + "=" * 90)
    print("METRIC A HOLDOUT - range prediction, trained on 2019-2025, tested on 2026")
    print("=" * 90)
    prior_o, prior_h = R.prior_close_table(con_orig), R.prior_close_table(con_hold)

    jobs = [("asian", "fixed_utc",
             R.session_ranges_fixed(con_orig, *R.FIXED_SESSIONS["asian"]),
             R.session_ranges_fixed(con_hold, *R.FIXED_SESSIONS["asian"]))]
    for name in ["london", "ny"]:
        jobs.append((name, "fixed_utc",
                     R.session_ranges_fixed(con_orig, *R.FIXED_SESSIONS[name]),
                     R.session_ranges_fixed(con_hold, *R.FIXED_SESSIONS[name])))
        sh, eh, tz = R.DST_SESSIONS[name]
        jobs.append((name, "dst_aware",
                     R.session_ranges_dst(con_orig, sh, eh, tz),
                     R.session_ranges_dst(con_hold, sh, eh, tz)))

    for name, mode, ranges_o, ranges_h in jobs:
        prior_o_days = ranges_o.merge(prior_o, on="day", how="inner")
        prior_h_days = ranges_h.merge(prior_h, on="day", how="inner")
        raw = pd.concat([prior_o_days, prior_h_days], ignore_index=True).sort_values("day").reset_index(drop=True)
        df = R.build_frame(raw[["day", "day_range"]], raw[["day", "prior_close"]])
        df = df.dropna(subset=["lag1_usd", "trail20_usd", "trail5_pct", "trail20_pct"])

        train = df[df["day"] < SPLIT_DATE]
        test = df[df["day"] >= SPLIT_DATE]
        if len(train) < 60 or len(test) < 10:
            print(f"\n{name}/{mode}: insufficient data (train={len(train)}, test={len(test)}), skipping")
            continue

        train_ratio_mean = train["ratio"].mean()
        q05, q10, q90, q95 = train["ratio"].quantile([0.05, 0.10, 0.90, 0.95])
        pc, actual = test["prior_close"].values, test["day_range"].values
        preds = {
            "pct_train": np.full(len(test), train_ratio_mean) * pc,
            "lag1_usd": test["lag1_usd"].values,
            "trail5_pct": test["trail5_pct"].values,
            "trail20_pct": test["trail20_pct"].values,
        }
        mae = {m: float(np.mean(np.abs(actual - p))) for m, p in preds.items()}
        mean_price = float(pc.mean())
        mae_pct = {m: v / mean_price * 100 for m, v in mae.items()}
        cov80 = float(np.mean((actual >= q10 * pc) & (actual <= q90 * pc)))
        cov90 = float(np.mean((actual >= q05 * pc) & (actual <= q95 * pc)))
        obs, lo, hi, p = R.block_bootstrap(np.abs(actual - preds["pct_train"]) - np.abs(actual - preds["trail20_pct"]))
        verdict = R.verdict(lo, hi)

        print(f"\n{name.upper()} | {mode} | train={len(train)} test={len(test)}  (mean 2026 prior_close ${mean_price:,.0f})")
        print(f"  MAE $:   pct_train={mae['pct_train']:.3f}  trail20_pct={mae['trail20_pct']:.3f}  "
              f"trail5_pct={mae['trail5_pct']:.3f}  lag1={mae['lag1_usd']:.3f}")
        print(f"  MAE %%:   pct_train={mae_pct['pct_train']:.3f}%%  trail20_pct={mae_pct['trail20_pct']:.3f}%%  "
              f"trail5_pct={mae_pct['trail5_pct']:.3f}%%  lag1={mae_pct['lag1_usd']:.3f}%%  "
              f"<- compare THIS row across periods, not the $ row")
        print(f"  diff (pct_train - trail20_pct) = {obs:+.3f} [{lo:+.3f},{hi:+.3f}] p={p:.3f} -> {verdict}")
        print(f"  interval coverage (from 2019-2025 quantiles): 80%={cov80:.2f}  90%={cov90:.2f}")
        rows_out.append({"metric": "A", "session": name, "mode": mode, "n_train": len(train), "n_test": len(test),
                         "mean_price": mean_price, **{f"mae_{k}": v for k, v in mae.items()},
                         **{f"mae_pct_{k}": v for k, v in mae_pct.items()}, "diff": obs, "ci_lo": lo, "ci_hi": hi,
                         "p": p, "verdict": verdict, "cov80": cov80, "cov90": cov90})


# ============================================================ Metric I ====
def score_transition(cur_tr, pri_tr, cur_te, pri_te):
    """Brier(model | trained on train) vs Brier(majority | trained on train), scored on test.
    Returns per-test-observation Brier arrays too, so the caller can bootstrap a CI on the gain."""
    valid_tr = (cur_tr >= 0) & (pri_tr >= 0)
    valid_te = (cur_te >= 0) & (pri_te >= 0)
    c_tr, p_tr = cur_tr[valid_tr], pri_tr[valid_tr]
    c_te, p_te = cur_te[valid_te], pri_te[valid_te]
    if len(c_tr) < 30 or len(c_te) < 10:
        return None
    T = np.zeros((3, 3))
    np.add.at(T, (p_tr, c_tr), 1)
    rows = T.sum(axis=1, keepdims=True)
    P = np.where(rows > 0, T / np.maximum(rows, 1), 1 / 3)
    maj = np.bincount(c_tr, minlength=3) / len(c_tr)
    onehot = np.eye(3)[c_te]
    model_brier = ((P[p_te] - onehot) ** 2).sum(axis=1)
    major_brier = ((maj[None, :] - onehot) ** 2).sum(axis=1)
    gain = (major_brier.mean() - model_brier.mean()) / major_brier.mean() * 100
    return {"n_train": len(c_tr), "n_test": len(c_te), "brier_model": float(model_brier.mean()),
            "brier_major": float(major_brier.mean()), "gain_pct": float(gain),
            "model_brier_arr": model_brier, "major_brier_arr": major_brier}


def metric_i_holdout(con_orig, con_hold, rows_out):
    print("\n" + "=" * 90)
    print("METRIC I HOLDOUT - intraday regime persistence, trained on 2019-2025, tested on 2026")
    print("=" * 90)
    for tf, cfg in I.TIMEFRAMES.items():
        ts_o, ratio_o = I.prepare(con_orig, cfg)
        ts_h, ratio_h = I.prepare(con_hold, cfg)
        ts = pd.concat([ts_o, ts_h], ignore_index=True)
        ratio = np.concatenate([ratio_o, ratio_h])
        order = np.argsort(ts.values)
        ts, ratio = ts.iloc[order].reset_index(drop=True), ratio[order]

        variants, _ = I.build_variants(ts, ratio, cfg)
        cur, prior = variants["deseas_prev_bar"] if cfg["intraday"] else variants["deseas_lag1"]
        split = np.datetime64(SPLIT_DATE, "ns")
        tr_mask, te_mask = ts.values < split, ts.values >= split
        r = score_transition(cur[tr_mask], prior[tr_mask], cur[te_mask], prior[te_mask])
        if r is None:
            print(f"\n{tf.upper()}: insufficient data, skipping")
            continue
        block_len = max(5, int(round(5 * 1440 / cfg["bar_min"])))
        diff_arr = r["major_brier_arr"] - r["model_brier_arr"]   # positive = model better
        obs, lo, hi = I.block_boot_ci(diff_arr, block_len)
        gain_lo = lo / r["brier_major"] * 100
        gain_hi = hi / r["brier_major"] * 100
        sig = "significant" if lo > 0 else ("significantly WORSE" if hi < 0 else "not significant")
        print(f"\n{tf.upper()}  n_train={r['n_train']:,}  n_test={r['n_test']:,}")
        print(f"  model_Brier={r['brier_model']:.4f}  majority_Brier={r['brier_major']:.4f}  "
              f"gain={r['gain_pct']:+.2f}%  95% CI [{gain_lo:+.2f}%,{gain_hi:+.2f}%]  -> {sig}")
        print(f"  (2019-2025 in-sample gain for reference: H4 ~+4%, H1 ~+5%, M30 ~+6%, D1 not established)")
        rows_out.append({"metric": "I", "timeframe": tf, "n_train": r["n_train"], "n_test": r["n_test"],
                         "brier_model": r["brier_model"], "brier_major": r["brier_major"],
                         "gain_pct": r["gain_pct"], "gain_ci_lo": gain_lo, "gain_ci_hi": gain_hi, "sig": sig})


def main(con_orig=None, con_hold=None):
    if con_orig is None:
        con_orig = duckdb.connect(ORIG_DB, read_only=True)
    if con_hold is None:
        con_hold = duckdb.connect(HOLDOUT_DB, read_only=True)
    for c in (con_orig, con_hold):
        c.execute("SET TimeZone='UTC'")

    rows_out = []
    metric_a_holdout(con_orig, con_hold, rows_out)
    metric_i_holdout(con_orig, con_hold, rows_out)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdout_2026_results.csv")
    pd.DataFrame(rows_out).to_csv(out, index=False)
    print(f"\nSaved: {out}")
    print("\nHow to read this: these are single train(2019-2025)/test(2026) splits, not a 6-combo matrix -")
    print("one number per session/timeframe, not six. Treat this as 'does the established conclusion still")
    print("hold on genuinely new data', not as a fresh robustness sweep in its own right.")


if __name__ == "__main__":
    main()