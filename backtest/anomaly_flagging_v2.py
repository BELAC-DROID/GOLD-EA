"""
Metric H re-test (v2): anomaly-flagging precision, both halves.

WHAT WAS WRONG WITH THE ORIGINAL (from reading both scripts):

  Part 1 - opening-range flag. The flag is "first-30-minute range is above the
  90th percentile of the previous 100 days". The ground truth was "the FULL
  session range is in the top 20%". But the first 30 minutes are PART OF the
  full session, so a big opening range mechanically raises the full-session
  range: the reported lift (e.g. ~3x for Asian) is partly part-whole overlap,
  not prediction. The correct ground truth for "does the opening range warn of
  an anomalous day" is the range of the REST of the session (after the first
  30 minutes). This script reports BOTH ground truths side by side so you can
  see how much of the original lift was overlap.

  Part 2 - calendar flag. "A whitelisted event's UTC time falls in the
  session's fixed UTC window." US releases print at 08:30 New York time =
  12:30 UTC in summer, 13:30 UTC in winter, so with a fixed 13-21 UTC NY window
  the summer releases fall OUTSIDE the NY window and inside London's. That
  makes the flag's composition seasonal. This script tests both the original
  fixed-UTC mapping and a DST-aware mapping (London/NY windows defined as
  08:00-16:00 local time, the event's local time compared to that).
  The calendar is known in advance, so using the full session as ground truth
  is legitimate here (no look-ahead, no part-whole leakage in the prediction
  sense).

Also new: no results are reported as "beats base rate" by point estimate only.
For each combo we report precision, base rate, lift, and a circular
block-bootstrap 95% CI on (precision - base rate), with codes:
   '+' significantly above base rate AND by >= MIN_MATERIAL_DIFF (3 pts; judgement call)
   't' significant but < 3 points (trivial)
   '0' no detectable difference
   '-' significantly BELOW base rate
   '.' too few flagged days
The flag rules themselves (90th-percentile opening range, 100-day trailing
window, 80th-percentile 'high' truth) are unchanged from the original.
The 6 window combos only define test periods (the flags are causal rolling
percentiles, nothing is fitted), and they overlap heavily: window-robustness,
not independent replication.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\anomaly_flagging_v2.py
Output: compact console summary + anomaly_flagging_v2_results.csv
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb
from numpy.lib.stride_tricks import sliding_window_view

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from walk_forward_matrix import COMBOS, generate_splits
import range_prediction_v3_baselines as R

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
MODELS_DIR = r"C:\Users\opc\gold_ea\models"

OPEN_MINUTES = 30
LOOKBACK = 100
OPEN_FLAG_PCTL = 90
HIGH_PCTL = 80
BLOCK_LEN = 10
N_BOOT = 1000
RNG_SEED = 21
MIN_FLAGGED = 15
MIN_MATERIAL_DIFF = 0.03


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def session_open_rest_full(con, start_h, end_h, tz=None):
    """Per day: opening range, rest-of-session range, full range (all in price units)."""
    s, e = start_h * 60, end_h * 60
    o_end = s + OPEN_MINUTES
    if tz is None:
        m, src = "minute_of_day", "minute_bars_ohlc"
    else:
        m = "(extract(hour FROM lt) * 60 + extract(minute FROM lt))"
        src = f"(SELECT *, timezone('{tz}', minute_ts::TIMESTAMPTZ) AS lt FROM minute_bars_ohlc)"
    df = con.execute(f"""
        SELECT date_trunc('day', minute_ts) AS day,
               max(high) FILTER (WHERE {m} >= {s} AND {m} < {o_end})
                 - min(low) FILTER (WHERE {m} >= {s} AND {m} < {o_end}) AS open_range,
               count(*) FILTER (WHERE {m} >= {s} AND {m} < {o_end}) AS n_open,
               max(high) FILTER (WHERE {m} >= {o_end} AND {m} < {e})
                 - min(low) FILTER (WHERE {m} >= {o_end} AND {m} < {e}) AS rest_range,
               count(*) FILTER (WHERE {m} >= {o_end} AND {m} < {e}) AS n_rest,
               max(high) FILTER (WHERE {m} >= {s} AND {m} < {e})
                 - min(low) FILTER (WHERE {m} >= {s} AND {m} < {e}) AS full_range,
               count(*) FILTER (WHERE {m} >= {s} AND {m} < {e}) AS n_full
        FROM {src}
        WHERE NOT (minute_of_day >= {R.CLOSURE_START_MIN} AND minute_of_day < {R.CLOSURE_END_MIN})
        GROUP BY day
        HAVING n_open > {OPEN_MINUTES * 0.5} AND n_rest > 30 AND n_full > 30
    """).fetchdf()
    df["day"] = R._to_naive_utc_day(df["day"])
    return df


def trailing_above(values, K, pctl):
    """values[i] > pctl-th percentile of the previous K values (strictly before i); NaN if undefined."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    out = np.full(n, np.nan)
    if n <= K:
        return out
    W = sliding_window_view(v[:-1], K)
    thr = np.percentile(W, pctl, axis=1)
    out[K:] = (v[K:] > thr).astype(float)
    return out


def build_flag_frame(raw, prior):
    df = raw.merge(prior, on="day", how="inner").sort_values("day").reset_index(drop=True)
    for c in ["open", "rest", "full"]:
        df[f"{c}_ratio"] = df[f"{c}_range"] / df["prior_close"]
    df["flag_open"] = trailing_above(df["open_ratio"].values, LOOKBACK, OPEN_FLAG_PCTL)
    df["high_full"] = trailing_above(df["full_ratio"].values, LOOKBACK, HIGH_PCTL)
    df["high_rest"] = trailing_above(df["rest_ratio"].values, LOOKBACK, HIGH_PCTL)
    return df


def load_event_config():
    sys.path.insert(0, MODELS_DIR)
    from spread_model import EVENT_NAME_WHITELIST, EVENT_CURRENCIES
    return EVENT_NAME_WHITELIST, EVENT_CURRENCIES


def open_calendar(con):
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")


def event_days(con, names, currs, start_h, end_h, tz=None):
    """Naive-UTC days on which a whitelisted event falls inside the session window."""
    s, e = start_h * 60, end_h * 60
    ts = "to_timestamp(timestamp_utc_ms/1000.0)"
    if tz is None:
        mm = f"(extract(hour FROM {ts}) * 60 + extract(minute FROM {ts}))"
    else:
        lt = f"timezone('{tz}', {ts}::TIMESTAMPTZ)"
        mm = f"(extract(hour FROM {lt}) * 60 + extract(minute FROM {lt}))"
    name_ph = ",".join("?" for _ in names)
    curr_ph = ",".join("?" for _ in currs)
    rows = con.execute(f"""
        SELECT DISTINCT date_trunc('day', {ts}) AS day
        FROM gold.calendar_events
        WHERE event_name IN ({name_ph}) AND currency IN ({curr_ph})
          AND {mm} >= {s} AND {mm} < {e}
    """, (*names, *currs)).fetchdf()
    return set(R._to_naive_utc_day(rows["day"])) if len(rows) else set()


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------
def score_flag(day, flag, actual, combo):
    """Precision vs base rate over the combo's pooled test days, with block-bootstrap CI."""
    f_all, a_all = [], []
    for s in generate_splits(combo):
        te = (day >= np.datetime64(s["test_start"], "ns")) & \
             (day < np.datetime64(s["test_end"], "ns") + np.timedelta64(1, "D"))
        if te.sum() < 10:
            continue
        f_all.append(flag[te])
        a_all.append(actual[te])
    if not f_all:
        return None
    f, a = np.concatenate(f_all).astype(bool), np.concatenate(a_all).astype(bool)
    n_fl = int(f.sum())
    if n_fl < MIN_FLAGGED:
        return {"n_days": len(f), "n_flagged": n_fl, "code": "."}
    precision, base = a[f].mean(), a.mean()

    n = len(f)
    L = max(1, min(BLOCK_LEN, n // 5))
    nb = int(np.ceil(n / L))
    starts = np.random.default_rng(RNG_SEED).integers(0, n, size=(N_BOOT, nb))
    idx = ((starts[:, :, None] + np.arange(L)[None, None, :]) % n).reshape(N_BOOT, -1)[:, :n]
    ff, aa = f[idx], a[idx]
    nf = ff.sum(axis=1)
    ok = nf > 0
    d = (np.where(ok, (ff & aa).sum(axis=1) / np.maximum(nf, 1), np.nan) - aa.mean(axis=1))[ok]
    lo, hi = np.percentile(d, [2.5, 97.5])
    diff = precision - base
    if lo > 0:
        code = "+" if diff >= MIN_MATERIAL_DIFF else "t"
    elif hi < 0:
        code = "-"
    else:
        code = "0"
    return {"n_days": n, "n_flagged": n_fl, "precision": precision, "base_rate": base,
            "lift": precision / base if base > 0 else float("nan"),
            "diff": diff, "ci_lo": lo, "ci_hi": hi, "code": code}


def run_flag(df, flag_col, truth_col, combo_list=COMBOS):
    d = df.dropna(subset=[flag_col, truth_col])
    day = d["day"].values
    return [(c["name"], score_flag(day, d[flag_col].values, d[truth_col].values, c)) for c in combo_list]


def summarise(label, results, rows, meta):
    codes = "".join(r["code"] if r else "." for _, r in results)
    ok = [r for _, r in results if r and "precision" in r]
    if ok:
        prec = np.mean([r["precision"] for r in ok])
        base = np.mean([r["base_rate"] for r in ok])
        lift = np.mean([r["lift"] for r in ok])
        nfl = int(np.mean([r["n_flagged"] for r in ok]))
        print(f"  {label:30s} codes[{'|'.join(codes)}]  flagged~{nfl:4d}  precision {prec:.3f} vs base {base:.3f}  lift {lift:.2f}x")
    else:
        print(f"  {label:30s} codes[{'|'.join(codes)}]  (too few flagged days)")
    for name, r in results:
        if r:
            rows.append({**meta, "truth": label, "combo": name, **r})


def main(con=None, open_calendar_fn=None, event_config=None):
    if con is None:
        con = duckdb.connect(ANALYTICS_DB, read_only=True)
    con.execute("SET TimeZone='UTC'")
    prior = R.prior_close_table(con)
    rows = []

    jobs = [("asian", "fixed_utc", session_open_rest_full(con, 0, 8))]
    for name in ["london", "ny"]:
        fs, fe = R.FIXED_SESSIONS[name]
        jobs.append((name, "fixed_utc", session_open_rest_full(con, fs, fe)))
        ls, le, tz = R.DST_SESSIONS[name]
        jobs.append((name, "dst_aware", session_open_rest_full(con, ls, le, tz)))

    print("=" * 84)
    print("PART 1 - opening-range flag (first 30 min > 90th pctl of previous 100 days)")
    print("  'full'  = original ground truth (full-session range in top 20%)  <- includes the flagged window itself")
    print("  'rest'  = corrected ground truth (range AFTER the first 30 min in top 20%)")
    print("=" * 84)
    frames = {}
    for name, mode, raw in jobs:
        df = build_flag_frame(raw, prior)
        frames[(name, mode)] = df
        print(f"\n{name.upper()} | {mode} | sessions={len(df)}")
        for truth in ["full", "rest"]:
            summarise(f"open-flag vs {truth}", run_flag(df, "flag_open", f"high_{truth}"), rows,
                      {"part": "opening_range", "session": name, "mode": mode})

    print("\n" + "=" * 84)
    print("PART 2 - calendar flag (whitelisted event inside the session window that day)")
    print("  ground truth = full-session range in top 20% (calendar is known in advance)")
    print("=" * 84)
    (open_calendar_fn or open_calendar)(con)
    names, currs = event_config or load_event_config()
    for name, mode, raw in jobs:
        df = frames[(name, mode)].copy()
        if name == "asian":
            s, e, tz = 0, 8, None
        elif mode == "fixed_utc":
            (s, e), tz = R.FIXED_SESSIONS[name], None
        else:
            s, e, tz = R.DST_SESSIONS[name]
        days = event_days(con, names, currs, s, e, tz)
        df["flag_cal"] = df["day"].isin(days).astype(float)
        print(f"\n{name.upper()} | {mode} | event-days in window: {len(days)}")
        summarise("calendar-flag vs full", run_flag(df, "flag_cal", "high_full"), rows,
                  {"part": "calendar", "session": name, "mode": mode})

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anomaly_flagging_v2_results.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\ncombo order: {' | '.join(c['name'] for c in COMBOS)}")
    print(f"codes: '+' sig above base rate by >= {MIN_MATERIAL_DIFF * 100:g} pts, 't' sig but trivial, '0' none, '-' sig below, '.' too few flagged")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()