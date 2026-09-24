"""
Phase 3, Test 1, Metric E v2a - session RANGE-ratio distribution stability.

This is the corrected version of the ORIGINAL distribution_shape_stability.py,
testing the same quantity that script actually computed (day_range /
prior_close - a range statistic, always positive) despite its docstring
calling it "daily session returns" (a return can be negative; a range
can't - these have very different skew/kurtosis behavior, so the two are
not interchangeable). See return_distribution_stability.py for the genuine
signed-return version of this question.

FIXES vs the original (found 2026-09-23 reviewing the script):
  1. No significance test before -> now a block-permutation test
     (distribution_stability_common.py) answers whether a fold's skew/kurt
     diff exceeds what an arbitrary split of the SAME data would produce.
     This almost certainly explains the extreme number already on record
     (Asian kurtosis "0.192 to 52.515 across folds" in the progress notes) -
     kurtosis is a high-variance statistic at small n, and the old n>=30
     floor allowed a single volatile day to dominate a 30-observation window.
  2. Fixed-UTC-only sessions -> now also runs DST-aware London/NY (Asian
     stays fixed UTC - Tokyo has no DST), reusing range_prediction_v3_baselines.py.
  3. No event-day accounting -> flags whitelisted high-impact event days
     (NFP/CPI/FOMC/GDP/PCE) and reports the diff with and without them, since
     a fold that happens to contain a surprise release will look
     "distributionally different" for a reason that has nothing to do with
     gold's tail behavior changing over time.
  4. No CSV output before -> now saved.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\distribution_shape_stability_v2a.py
Output: console tables + distribution_shape_stability_v2a_results.csv
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import range_prediction_v3_baselines as R
from distribution_stability_common import fold_summary, MIN_N
from walk_forward_matrix import COMBOS, generate_splits

sys.path.insert(0, r"C:\Users\opc\gold_ea\models")
from spread_model import EVENT_NAME_WHITELIST, EVENT_CURRENCIES

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"


def get_event_days(con):
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")
    name_ph = ",".join("?" for _ in EVENT_NAME_WHITELIST)
    curr_ph = ",".join("?" for _ in EVENT_CURRENCIES)
    rows = con.execute(f"""
        SELECT DISTINCT date_trunc('day', to_timestamp(timestamp_utc_ms/1000.0)) AS day
        FROM gold.calendar_events
        WHERE event_name IN ({name_ph}) AND currency IN ({curr_ph})
    """, (*EVENT_NAME_WHITELIST, *EVENT_CURRENCIES)).fetchdf()
    return set(R._to_naive_utc_day(rows["day"])) if len(rows) else set()


def run_session(df, event_days, name, mode, rows_out):
    df = df.dropna(subset=["ratio"]).sort_values("day")
    is_event = df["day"].isin(event_days).values
    print(f"\n{'=' * 78}\n{name.upper()} | {mode} | sessions={len(df)}  ({is_event.sum()} event days)")
    for combo in COMBOS:
        print(f"\n  --- {combo['name']} ---")
        for s in generate_splits(combo):
            tr_mask = (df["day"] >= s["train_start"]) & (df["day"] <= s["train_end"])
            te_mask = (df["day"] >= s["test_start"]) & (df["day"] <= s["test_end"])
            train, test = df.loc[tr_mask, "ratio"].values, df.loc[te_mask, "ratio"].values
            r = fold_summary(train, test)
            if r is None:
                continue
            warn = " (kurtosis: LOW-N, treat cautiously)" if r["low_n_kurtosis_warning"] else ""
            sig = []
            if r["p_skew"] < 0.05:
                sig.append("skew")
            if r["p_kurt"] < 0.05:
                sig.append("kurt")
            sig_str = "/".join(sig) if sig else "none"
            print(f"    {s['test_start']}->{s['test_end']}  n_tr={r['n_train']:4d} n_te={r['n_test']:4d}  "
                  f"skew_diff={r['skew_diff']:.3f}(p={r['p_skew']:.3f})  "
                  f"kurt_diff={r['kurt_diff']:.3f}(p={r['p_kurt']:.3f})  sig=[{sig_str}]{warn}")

            # same fold, event days excluded - does the conclusion change?
            tr_ex = df.loc[tr_mask & ~is_event, "ratio"].values
            te_ex = df.loc[te_mask & ~is_event, "ratio"].values
            r_ex = fold_summary(tr_ex, te_ex)
            row = {"session": name, "mode": mode, "combo": combo["name"], "test_start": s["test_start"],
                   "test_end": s["test_end"], **{f"all_{k}": v for k, v in r.items() if k != "label"}}
            if r_ex is not None:
                row.update({f"exevt_{k}": v for k, v in r_ex.items() if k != "label"})
                if (r["p_skew"] < 0.05) != (r_ex["p_skew"] < 0.05) or (r["p_kurt"] < 0.05) != (r_ex["p_kurt"] < 0.05):
                    print(f"      NOTE: excluding event days changes significance "
                          f"(ex-event: skew_diff={r_ex['skew_diff']:.3f} p={r_ex['p_skew']:.3f}, "
                          f"kurt_diff={r_ex['kurt_diff']:.3f} p={r_ex['p_kurt']:.3f})")
            rows_out.append(row)


def main(con=None):
    if con is None:
        con = duckdb.connect(ANALYTICS_DB, read_only=True)
    con.execute("SET TimeZone='UTC'")
    prior = R.prior_close_table(con)
    event_days = get_event_days(con)
    print(f"whitelisted high-impact event days found: {len(event_days)}")

    jobs = [("asian", "fixed_utc", R.session_ranges_fixed(con, *R.FIXED_SESSIONS["asian"]))]
    for name in ["london", "ny"]:
        jobs.append((name, "fixed_utc", R.session_ranges_fixed(con, *R.FIXED_SESSIONS[name])))
        sh, eh, tz = R.DST_SESSIONS[name]
        jobs.append((name, "dst_aware", R.session_ranges_dst(con, sh, eh, tz)))

    rows_out = []
    for name, mode, ranges in jobs:
        df = R.build_frame(ranges, prior)
        run_session(df, event_days, name, mode, rows_out)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "distribution_shape_stability_v2a_results.csv")
    pd.DataFrame(rows_out).to_csv(out, index=False)
    print(f"\nSaved: {out}")
    print(f"\nMIN_N for any test = {MIN_N}; kurtosis flagged low-confidence below 60 observations per side.")
    print("Reminder: skew differences are detectable at smaller n than kurtosis differences - a kurtosis")
    print("finding with a 'LOW-N' warning should be weighted much less than a skew finding without one.")


if __name__ == "__main__":
    main()