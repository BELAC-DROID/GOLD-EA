"""
Metric G re-test (v3): session-open (first 30 minutes) range prediction.

Original Metric G had the same structure as the original Metric A: a
training-mean percentage-of-prior-close model vs "yesterday's opening range"
(lag-1). Metric A's re-test showed that lag-1 is a weak baseline - a trailing
20-session average did as well or better than the training-mean model in every
session - so Metric G's "beats naive in all 6 combos" is expected to shrink the
same way. This script applies the identical Metric A v3 treatment to the
opening range:
  * baselines: lag-1, trailing 5/20-session mean (as % of prior close), and a
    dollar trailing-20 reference; all scored on identical test days
  * pre-committed primary comparison: pct_train vs trail20_pct
  * circular block-bootstrap 95% CI + p-value on the paired MAE difference
  * 80%/90% interval coverage
  * London/NY run under both session definitions (fixed UTC vs local-time
    opens, DST-aware); Asian stays fixed UTC (Tokyo: no DST)

It reuses the evaluation code from range_prediction_v3_baselines.py (same
directory), so the two metrics are scored identically.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\session_open_prediction_v3.py
Output: console table + session_open_prediction_v3_results.csv
"""

import os
import sys
import pandas as pd
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import range_prediction_v3_baselines as R
from walk_forward_matrix import COMBOS

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
OPEN_MINUTES = 30
MIN_BARS = OPEN_MINUTES * 0.5   # same completeness rule as the original script

# (open hour, mode, tz). Fixed-UTC opens match the original Metric G script.
FIXED_OPEN_HOUR = {"asian": 0, "london": 8, "ny": 13}
DST_OPEN = {"london": (8, "Europe/London"), "ny": (8, "America/New_York")}


def opening_ranges(con, open_hour, tz=None):
    s, e = open_hour * 60, open_hour * 60 + OPEN_MINUTES
    if tz is None:
        m = "minute_of_day"
        src = "minute_bars_ohlc"
    else:
        m = "(extract(hour FROM lt) * 60 + extract(minute FROM lt))"
        src = f"(SELECT *, timezone('{tz}', minute_ts::TIMESTAMPTZ) AS lt FROM minute_bars_ohlc)"
    df = con.execute(f"""
        SELECT date_trunc('day', minute_ts) AS day, (max(high) - min(low)) AS day_range
        FROM {src}
        WHERE {m} >= {s} AND {m} < {e}
          AND NOT (minute_of_day >= {R.CLOSURE_START_MIN} AND minute_of_day < {R.CLOSURE_END_MIN})
        GROUP BY day HAVING count(*) > {MIN_BARS}
    """).fetchdf()
    df["day"] = R._to_naive_utc_day(df["day"])
    return df


def main(con=None):
    if con is None:
        con = duckdb.connect(ANALYTICS_DB, read_only=True)
    con.execute("SET TimeZone='UTC'")
    prior = R.prior_close_table(con)

    jobs = [("asian", "fixed_utc", opening_ranges(con, FIXED_OPEN_HOUR["asian"]))]
    for name in ["london", "ny"]:
        jobs.append((name, "fixed_utc", opening_ranges(con, FIXED_OPEN_HOUR[name])))
        h, tz = DST_OPEN[name]
        jobs.append((name, "dst_aware", opening_ranges(con, h, tz)))

    rows = []
    for name, mode, ranges in jobs:
        df = R.build_frame(ranges, prior)
        print(f"\n=== {name.upper()} first {OPEN_MINUTES} min | {mode} | sessions={len(df)} ===")
        print(f"{'combo':22s} {'days':>5s} {'MAE_pct':>8s} {'MAE_t20p':>9s} {'MAE_t5p':>8s} {'MAE_lag1':>9s} | "
              f"{'diff vs t20p [95% CI]':>28s} {'p':>6s} {'verdict':>22s} | {'cov80':>5s} {'cov90':>5s}")
        for combo in COMBOS:
            r = R.evaluate(df, combo)
            if r is None:
                print(f"{combo['name']:22s} no valid folds")
                continue
            b = R.PRIMARY_BASELINE
            v = R.verdict(r[f"ci_lo_{b}"], r[f"ci_hi_{b}"])
            print(f"{combo['name']:22s} {r['n_days']:5d} {r['mae_pct_train']:8.3f} {r['mae_trail20_pct']:9.3f} "
                  f"{r['mae_trail5_pct']:8.3f} {r['mae_lag1_usd']:9.3f} | "
                  f"{r[f'diff_vs_{b}']:+7.3f} [{r[f'ci_lo_{b}']:+7.3f},{r[f'ci_hi_{b}']:+7.3f}] "
                  f"{r[f'p_{b}']:6.3f} {v:>22s} | {r['cov80']:5.2f} {r['cov90']:5.2f}")
            rows.append({"session": name, "mode": mode, "combo": combo["name"], "verdict_primary": v, **r})

    res = pd.DataFrame(rows)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_open_prediction_v3_results.csv")
    res.to_csv(out, index=False)
    print("\n" + "=" * 90)
    print("SUMMARY - primary comparison (pct_train vs trail20_pct), verdict counts per session/mode")
    print(res.groupby(["session", "mode"])["verdict_primary"].value_counts().to_string())
    print(f"\nSaved: {out}")
    print("Reminder: combos overlap heavily (window-robustness, not independent replication).")


if __name__ == "__main__":
    main()