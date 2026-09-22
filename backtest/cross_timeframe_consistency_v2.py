"""
Metric I re-test (v2) - cross-timeframe volatility-regime persistence.

WHY: the original result ("H1 has essentially no regime signal, M30 mixed,
H4/D1 robust") may be a measurement artifact. Reading cross_timeframe_
consistency.py, two design features could produce it without gold actually
lacking hourly volatility clustering:

  (1) TIME-OF-DAY CONTAMINATION. A bar is labelled low/normal/high by ranking
      its range against ALL bars in a trailing window. At H1/M30 the label is
      then mostly "what hour is it" (e.g. 14:00 UTC is almost always 'high',
      03:00 almost always 'low'), not "is volatility currently elevated".
  (2) HORIZON + NOISE. The test asks whether the regime of a single bar
      ~33 calendar days ago predicts the current bar's regime. A single
      hourly bar's range is a very noisy volatility proxy, and 33 days is a
      long lag; clustering is strongest at short lags. (Metric C's daily
      test used a lag of 1 day.)

WHAT THIS SCRIPT DOES (each change tested separately so the cause is clear):
  orig_33d              exact original method (control - should reproduce the
                        old win counts: D1 6/6, H4 6/6, M30 4/6, H1 1/6)
  deseas_*  variants    label = rank of the bar's range among the previous
                        SLOT_K observations of the SAME time-of-day slot
                        (causal, removes time-of-day effect), then tested at
                        three lags:
    deseas_prev_bar       previous bar (D1: previous day) - tradeable horizon
    deseas_same_slot_1d   same time slot, previous trading day (intraday only)
    deseas_lag23          same slot ~23 trading days (~33 calendar days) back
                          = the ORIGINAL horizon with the NEW labelling

  Reading the results:
    orig_33d vs deseas_lag23   -> effect of fixing time-of-day labelling
    deseas_lag23 vs prev_bar / same_slot_1d -> effect of horizon

Scoring: same Brier-vs-majority transition test as the original, but
vectorised, with a circular block-bootstrap 95% CI on the paired Brier
difference (model minus majority) pooled over each combo's test folds.
'+' = model significantly better, '-' = significantly worse, '0' = no
significant difference, '.' = no valid folds. Same 6-combo window matrix
(overlapping test periods: robustness to window choice, NOT 6 independent
tests). Small deviation from the original: fold end dates are inclusive of
the whole end day.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\cross_timeframe_consistency_v2.py
Output: compact console summary + cross_timeframe_consistency_v2_results.csv
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb
from numpy.lib.stride_tricks import sliding_window_view

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

TIMEFRAMES = {
    "d1":  {"table": "bars_d1",  "orig_lookback": 100,  "orig_stride": 33,   "bar_min": 1440, "intraday": False},
    "h4":  {"table": "bars_h4",  "orig_lookback": 600,  "orig_stride": 200,  "bar_min": 240,  "intraday": True},
    "h1":  {"table": "bars_h1",  "orig_lookback": 2400, "orig_stride": 800,  "bar_min": 60,   "intraday": True},
    "m30": {"table": "bars_m30", "orig_lookback": 4800, "orig_stride": 1600, "bar_min": 30,   "intraday": True},
}

SLOT_K = 100            # trailing same-slot observations (~100 trading days, matches D1 lookback)
LAG_MONTH_OBS = 23      # ~33 calendar days in trading days
MIN_SLOT_OBS = 200      # drop odd time slots with too few bars
LOW_PCTL, HIGH_PCTL = 20, 80
N_BOOT = 1000
RNG_SEED = 7


# ----------------------------------------------------------------------------
# Labelling
# ----------------------------------------------------------------------------
def trailing_labels(v, K, chunk=2000):
    """0=low,1=normal,2=high vs the previous K values (strictly before i). -1 = undefined."""
    n = len(v)
    out = np.full(n, -1, dtype=int)
    if n <= K:
        return out
    W = sliding_window_view(v[:-1], K)          # window j = v[j:j+K] -> labels bar i=j+K
    for a in range(0, len(W), chunk):
        w = W[a:a + chunk]
        lo, hi = np.percentile(w, [LOW_PCTL, HIGH_PCTL], axis=1)
        cur = v[K + a: K + a + len(w)]
        out[K + a: K + a + len(w)] = np.where(cur < lo, 0, np.where(cur > hi, 2, 1))
    return out


def prepare(con, cfg):
    df = con.execute(f"""
        SELECT bar_ts, high, low, LAG(close) OVER (ORDER BY bar_ts) AS prior_close
        FROM {cfg['table']} WHERE close IS NOT NULL ORDER BY bar_ts
    """).fetchdf().dropna(subset=["prior_close"])
    ts = pd.to_datetime(df["bar_ts"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    ratio = ((df["high"] - df["low"]) / df["prior_close"]).values.astype(float)
    return ts.reset_index(drop=True), ratio


def build_variants(ts, ratio, cfg):
    n = len(ratio)
    intraday = cfg["intraday"]
    variants = {}

    cur_o = trailing_labels(ratio, cfg["orig_lookback"])
    prior_o = np.full(n, -1, dtype=int)
    s = cfg["orig_stride"]
    prior_o[s:] = cur_o[:-s]
    variants["orig_33d"] = (cur_o, prior_o)

    slot = (ts.dt.hour * 60 + ts.dt.minute).values if intraday else np.zeros(n, dtype=int)
    lab = np.full(n, -1, dtype=int)
    slot_idx = {}
    for sv in np.unique(slot):
        idx = np.where(slot == sv)[0]
        if intraday and len(idx) < MIN_SLOT_OBS:
            continue
        slot_idx[sv] = idx
        lab[idx] = trailing_labels(ratio[idx], SLOT_K)

    prior = np.full(n, -1, dtype=int)
    prior[1:] = lab[:-1]
    if intraday:  # ignore pairs separated by weekends/holidays/long gaps
        gap_min = ((ts.values[1:] - ts.values[:-1]).astype("timedelta64[m]").astype(int))
        bad = np.concatenate([[True], gap_min > 3 * cfg["bar_min"]])
        prior[bad] = -1
        variants["deseas_prev_bar"] = (lab, prior)
        p1 = np.full(n, -1, dtype=int)
        for idx in slot_idx.values():
            p1[idx[1:]] = lab[idx[:-1]]
        variants["deseas_same_slot_1d"] = (lab, p1)
    else:
        variants["deseas_lag1"] = (lab, prior)

    p23 = np.full(n, -1, dtype=int)
    for idx in slot_idx.values():
        p23[idx[LAG_MONTH_OBS:]] = lab[idx[:-LAG_MONTH_OBS]]
    variants["deseas_lag23"] = (lab, p23)
    return variants, slot


def slot_spread(lab, slot, code=2):
    """min/max over time slots of P(label==code) - flat ~0.20 means no time-of-day effect."""
    shares = []
    for sv in np.unique(slot):
        m = (slot == sv) & (lab >= 0)
        if m.sum() >= MIN_SLOT_OBS:
            shares.append(np.mean(lab[m] == code))
    return (min(shares), max(shares)) if shares else (float("nan"), float("nan"))


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------
def block_boot_ci(d, L, n_boot=N_BOOT, seed=RNG_SEED):
    n = len(d)
    L = max(1, min(L, n))
    ext = np.concatenate([d, d[:L]])
    cs = np.concatenate([[0.0], np.cumsum(ext)])
    bs = cs[L:L + n] - cs[:n]                       # sum of the L-block starting at each i
    nb = int(np.ceil(n / L))
    starts = np.random.default_rng(seed).integers(0, n, size=(n_boot, nb))
    means = bs[starts].sum(axis=1) / (nb * L)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return d.mean(), lo, hi


def eval_combo(ts_vals, cur, prior, combo, block_len):
    valid = (cur >= 0) & (prior >= 0)
    day, c, p = ts_vals[valid], cur[valid], prior[valid]
    model_all, major_all = [], []
    for s in generate_splits(combo):
        tr = (day >= np.datetime64(s["train_start"], "ns")) & \
             (day < np.datetime64(s["train_end"], "ns") + np.timedelta64(1, "D"))
        te = (day >= np.datetime64(s["test_start"], "ns")) & \
             (day < np.datetime64(s["test_end"], "ns") + np.timedelta64(1, "D"))
        if tr.sum() < 30 or te.sum() < 10:
            continue
        T = np.zeros((3, 3))
        np.add.at(T, (p[tr], c[tr]), 1)
        rows = T.sum(axis=1, keepdims=True)
        P = np.where(rows > 0, T / np.maximum(rows, 1), 1 / 3)
        maj = np.bincount(c[tr], minlength=3) / tr.sum()
        onehot = np.eye(3)[c[te]]
        model_all.append(((P[p[te]] - onehot) ** 2).sum(axis=1))
        major_all.append(((maj[None, :] - onehot) ** 2).sum(axis=1))
    if not model_all:
        return None
    m, j = np.concatenate(model_all), np.concatenate(major_all)
    obs, lo, hi = block_boot_ci(m - j, block_len)
    code = "+" if hi < 0 else ("-" if lo > 0 else "0")
    return {"n_test": len(m), "brier_model": m.mean(), "brier_major": j.mean(),
            "diff": obs, "ci_lo": lo, "ci_hi": hi, "code": code}


def main():
    con = duckdb.connect(ANALYTICS_DB, read_only=True)
    rows, summary = [], []
    for tf, cfg in TIMEFRAMES.items():
        ts, ratio = prepare(con, cfg)
        variants, slot = build_variants(ts, ratio, cfg)
        block_len = max(5, int(round(5 * 1440 / cfg["bar_min"])))   # ~1 trading week of bars
        print(f"\n{'=' * 78}\n{tf.upper()}  bars={len(ratio):,}  block_len={block_len}")
        if cfg["intraday"]:
            lo_o, hi_o = slot_spread(variants["orig_33d"][0], slot)
            lo_d, hi_d = slot_spread(variants["deseas_prev_bar"][0], slot)
            print(f"  time-of-day check - P(label='high') across time slots (flat would be ~0.20):")
            print(f"    original labels : min {lo_o:.2f}  max {hi_o:.2f}")
            print(f"    deseasonalized  : min {lo_d:.2f}  max {hi_d:.2f}")
        ts_vals = ts.values
        for vname, (cur, prior) in variants.items():
            codes, gains = [], []
            for combo in COMBOS:
                r = eval_combo(ts_vals, cur, prior, combo, block_len)
                if r is None:
                    codes.append(".")
                    continue
                codes.append(r["code"])
                gains.append((r["brier_major"] - r["brier_model"]) / r["brier_major"] * 100)
                rows.append({"timeframe": tf, "variant": vname, "combo": combo["name"], **r})
            summary.append((tf, vname, "".join(codes), np.mean(gains) if gains else float("nan")))
            print(f"  {vname:22s} combos[{'|'.join(codes)}]  mean Brier gain vs majority {summary[-1][3]:+.2f}%")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cross_timeframe_consistency_v2_results.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\n{'=' * 78}\nSUMMARY  (combo order: {' | '.join(c['name'] for c in COMBOS)})")
    print("  + model sig. better than majority, 0 no sig. difference, - sig. worse, . no folds")
    print(f"{'timeframe':10s} {'variant':22s} {'combos':>13s} {'mean gain %':>12s}")
    for tf, vname, codes, g in summary:
        print(f"{tf:10s} {vname:22s} {'|'.join(codes):>13s} {g:+12.2f}")
    print(f"\nSaved: {out}")
    print("Reminder: combos overlap heavily (window-robustness, not independent replication).")


if __name__ == "__main__":
    main()