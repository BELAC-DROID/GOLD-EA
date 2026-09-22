"""
Metric A re-test (v3) - range prediction, tightened per the 2026-09-21
external validation review (gold-ea-ai-decision-layer.md, Section 7.4).

WHAT CHANGED vs range_prediction_window_matrix.py
  1. Stronger baselines. The old "naive" was yesterday's single session range
     (one noisy observation). Now also: trailing 5- and 20-session mean range,
     both as a % of prior close (consistent with the no-fixed-dollar lesson)
     and one dollar-based 20-session reference.
  2. Same-sample scoring. Every model is scored on exactly the same test days
     (the old script scored the model on n days and naive on n-1 per fold).
     Baselines use only information available before each test day.
  3. Significance. Circular block bootstrap on the paired absolute-error
     difference (model minus baseline) -> 95% CI and p-value, instead of
     "beats naive: yes/no".
  4. Calibration. Empirical coverage of 80% and 90% central prediction
     intervals (quantiles of training-window range/prior_close), which is what
     Section 7.3 of the design doc actually specifies.
  5. Session definition A/B. "fixed_utc" = original hours. "dst_aware" =
     London 08:00-16:00 Europe/London local, NY 08:00-16:00 America/New_York
     local (Asian stays fixed UTC: Tokyo has no DST). The original fixed UTC
     hours only match local time in WINTER.

PRE-COMMITTED PRIMARY COMPARISON (decided before running, to avoid choosing
the baseline after seeing results):
    pct_train  vs  trail20_pct
All other comparisons are secondary/descriptive. The window matrix combos are
the same 6 as before (walk_forward_matrix.py); note they share heavily
overlapping test periods, so they are NOT independent replications.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\range_prediction_v3_baselines.py
Output: console tables + range_prediction_v3_results.csv next to this script.
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

# Closure (rollover) exclusion kept in UTC, identical to the original script,
# so the only thing that differs between modes is the session window itself.
CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60

FIXED_SESSIONS = {"asian": (0, 8), "london": (8, 16), "ny": (13, 21)}
DST_SESSIONS = {  # (start_h, end_h, IANA tz) in LOCAL time
    "london": (8, 16, "Europe/London"),
    "ny": (8, 16, "America/New_York"),
}

BLOCK_LEN = 10       # bootstrap block length (sessions); keeps short-range dependence
N_BOOT = 2000
RNG_SEED = 42

MODELS = ["pct_train", "lag1_usd", "trail5_pct", "trail20_pct", "trail20_usd"]
PRIMARY_BASELINE = "trail20_pct"


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def _to_naive_utc_day(series):
    d = pd.to_datetime(series)
    if getattr(d.dt, "tz", None) is not None:
        d = d.dt.tz_convert("UTC").dt.tz_localize(None)
    return d.dt.normalize()


def prior_close_table(con):
    df = con.execute("""
        WITH daily_close AS (
            SELECT date_trunc('day', minute_ts) AS day, arg_max(close, minute_ts) AS day_close
            FROM minute_bars_ohlc GROUP BY day
        )
        SELECT day, LAG(day_close) OVER (ORDER BY day) AS prior_close FROM daily_close
    """).fetchdf()
    df["day"] = _to_naive_utc_day(df["day"])
    return df.dropna(subset=["prior_close"])


def session_ranges_fixed(con, start_h, end_h):
    s, e = start_h * 60, end_h * 60
    df = con.execute(f"""
        SELECT date_trunc('day', minute_ts) AS day, (max(high) - min(low)) AS day_range
        FROM minute_bars_ohlc
        WHERE minute_of_day >= {s} AND minute_of_day < {e}
          AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        GROUP BY day HAVING count(*) > 30
    """).fetchdf()
    df["day"] = _to_naive_utc_day(df["day"])
    return df


def session_ranges_dst(con, start_h, end_h, tz):
    s, e = start_h * 60, end_h * 60
    df = con.execute(f"""
        WITH b AS (
            SELECT minute_ts, high, low, minute_of_day,
                   timezone('{tz}', minute_ts::TIMESTAMPTZ) AS local_ts
            FROM minute_bars_ohlc
        ), c AS (
            SELECT minute_ts, high, low, minute_of_day,
                   (extract(hour FROM local_ts) * 60 + extract(minute FROM local_ts)) AS lmin
            FROM b
        )
        SELECT date_trunc('day', minute_ts) AS day, (max(high) - min(low)) AS day_range
        FROM c
        WHERE lmin >= {s} AND lmin < {e}
          AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        GROUP BY day HAVING count(*) > 30
    """).fetchdf()
    df["day"] = _to_naive_utc_day(df["day"])
    return df


def build_frame(ranges, prior):
    df = ranges.merge(prior, on="day", how="inner").sort_values("day").reset_index(drop=True)
    df["ratio"] = df["day_range"] / df["prior_close"]
    # Baselines: only information available BEFORE each day (shift(1) first).
    df["lag1_usd"] = df["day_range"].shift(1)
    df["trail20_usd"] = df["day_range"].shift(1).rolling(20).mean()
    df["trail5_pct"] = df["ratio"].shift(1).rolling(5).mean() * df["prior_close"]
    df["trail20_pct"] = df["ratio"].shift(1).rolling(20).mean() * df["prior_close"]
    return df


# ----------------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------------
def block_bootstrap(d, block=BLOCK_LEN, n_boot=N_BOOT, seed=RNG_SEED):
    """Circular block bootstrap of the mean of a (time-ordered) series d."""
    d = np.asarray(d, dtype=float)
    n = len(d)
    rng = np.random.default_rng(seed)
    nblocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, nblocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    idx = idx.reshape(n_boot, -1)[:, :n]
    means = d[idx].mean(axis=1)
    obs = d.mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    p = float(np.mean(np.abs(means - obs) >= abs(obs)))
    return obs, lo, hi, p


def verdict(lo, hi):
    if hi < 0:
        return "MODEL better (sig)"
    if lo > 0:
        return "BASELINE better (sig)"
    return "no sig difference"


# ----------------------------------------------------------------------------
# Walk-forward evaluation
# ----------------------------------------------------------------------------
def evaluate(df, combo):
    """Returns dict of pooled results for one combo, or None if no valid folds."""
    abs_err = {m: [] for m in MODELS}
    cover80, cover90 = [], []
    n_folds_used = 0
    for s in generate_splits(combo):
        train = df[(df["day"] >= s["train_start"]) & (df["day"] <= s["train_end"])]
        test = df[(df["day"] >= s["test_start"]) & (df["day"] <= s["test_end"])]
        test = test.dropna(subset=["lag1_usd", "trail20_usd", "trail5_pct", "trail20_pct"])
        if len(train) < 60 or len(test) < 2:
            continue
        n_folds_used += 1
        actual = test["day_range"].values
        pc = test["prior_close"].values
        train_ratio = train["ratio"]
        preds = {
            "pct_train": train_ratio.mean() * pc,
            "lag1_usd": test["lag1_usd"].values,
            "trail5_pct": test["trail5_pct"].values,
            "trail20_pct": test["trail20_pct"].values,
            "trail20_usd": test["trail20_usd"].values,
        }
        for m in MODELS:
            abs_err[m].extend(np.abs(actual - preds[m]))
        q05, q10, q90, q95 = train_ratio.quantile([0.05, 0.10, 0.90, 0.95])
        cover80.extend((actual >= q10 * pc) & (actual <= q90 * pc))
        cover90.extend((actual >= q05 * pc) & (actual <= q95 * pc))
    if n_folds_used == 0:
        return None
    err = {m: np.array(v) for m, v in abs_err.items()}
    out = {
        "n_folds": n_folds_used,
        "n_days": len(err["pct_train"]),
        "cov80": float(np.mean(cover80)),
        "cov90": float(np.mean(cover90)),
    }
    for m in MODELS:
        out[f"mae_{m}"] = float(err[m].mean())
    # Paired differential vs each baseline (model minus baseline; negative = model better)
    for b in ["lag1_usd", "trail5_pct", "trail20_pct", "trail20_usd"]:
        obs, lo, hi, p = block_bootstrap(err["pct_train"] - err[b])
        out[f"diff_vs_{b}"] = obs
        out[f"ci_lo_{b}"] = lo
        out[f"ci_hi_{b}"] = hi
        out[f"p_{b}"] = p
    return out


def main():
    con = duckdb.connect(ANALYTICS_DB, read_only=True)
    con.execute("SET TimeZone='UTC'")

    # ---- sanity checks before trusting anything ----
    print("minute_ts type:", con.execute("SELECT typeof(minute_ts) FROM minute_bars_ohlc LIMIT 1").fetchone()[0])
    try:
        chk = con.execute("""
            SELECT timezone('Europe/London', TIMESTAMPTZ '2024-01-15 12:00:00+00'),
                   timezone('Europe/London', TIMESTAMPTZ '2024-07-15 12:00:00+00'),
                   timezone('America/New_York', TIMESTAMPTZ '2024-01-15 12:00:00+00'),
                   timezone('America/New_York', TIMESTAMPTZ '2024-07-15 12:00:00+00')
        """).fetchone()
        print("DST sanity (12:00 UTC -> London Jan/Jul, NY Jan/Jul):", chk)
        print("  expected: London 12:00 / 13:00, NY 07:00 / 08:00\n")
    except Exception as ex:  # ICU extension missing -> DST mode cannot run
        print("DST conversion unavailable (ICU?):", ex)
        print("Try: con.execute('INSTALL icu; LOAD icu;') or upgrade duckdb. Aborting.")
        return

    prior = prior_close_table(con)
    rows = []

    jobs = [("asian", "fixed_utc", session_ranges_fixed(con, *FIXED_SESSIONS["asian"]))]
    for name in ["london", "ny"]:
        jobs.append((name, "fixed_utc", session_ranges_fixed(con, *FIXED_SESSIONS[name])))
        sh, eh, tz = DST_SESSIONS[name]
        jobs.append((name, "dst_aware", session_ranges_dst(con, sh, eh, tz)))

    for name, mode, ranges in jobs:
        df = build_frame(ranges, prior)
        print(f"\n=== {name.upper()} | mode={mode} | sessions={len(df)} ===")
        print(f"{'combo':22s} {'days':>5s} {'MAE_pct':>8s} {'MAE_t20p':>9s} {'MAE_t5p':>8s} "
              f"{'MAE_lag1':>9s} | {'diff vs t20p [95% CI]':>30s} {'p':>6s} {'verdict':>22s} | "
              f"{'cov80':>6s} {'cov90':>6s}")
        for combo in COMBOS:
            r = evaluate(df, combo)
            if r is None:
                print(f"{combo['name']:22s} no valid folds")
                continue
            b = PRIMARY_BASELINE
            v = verdict(r[f"ci_lo_{b}"], r[f"ci_hi_{b}"])
            print(f"{combo['name']:22s} {r['n_days']:5d} {r['mae_pct_train']:8.3f} {r['mae_trail20_pct']:9.3f} "
                  f"{r['mae_trail5_pct']:8.3f} {r['mae_lag1_usd']:9.3f} | "
                  f"{r[f'diff_vs_{b}']:+8.3f} [{r[f'ci_lo_{b}']:+7.3f},{r[f'ci_hi_{b}']:+7.3f}] "
                  f"{r[f'p_{b}']:6.3f} {v:>22s} | {r['cov80']:6.2f} {r['cov90']:6.2f}")
            row = {"session": name, "mode": mode, "combo": combo["name"], "verdict_primary": v}
            row.update(r)
            rows.append(row)

    res = pd.DataFrame(rows)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "range_prediction_v3_results.csv")
    res.to_csv(out, index=False)

    print("\n" + "=" * 100)
    print("SUMMARY - primary comparison (pct_train vs trail20_pct), count of combos per verdict")
    print("=" * 100)
    print(res.groupby(["session", "mode"])["verdict_primary"].value_counts().to_string())
    print("\nTarget coverage: cov80 ~ 0.80, cov90 ~ 0.90. Large deviations = miscalibrated intervals.")
    print(f"Saved: {out}")
    print("Reminder: the 6 combos overlap heavily - read them as window-robustness, not 6 independent tests.")


if __name__ == "__main__":
    main()