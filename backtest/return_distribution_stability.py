"""
Metric E v2b - session RETURN distribution stability (the genuine version
of what "distribution shape stability" implies for risk-model assumptions:
a signed return, not a range statistic).

The original distribution_shape_stability.py's docstring called its subject
"daily session returns" but it actually measured day_range / prior_close - a
strictly positive range, which cannot have negative skew and behaves very
differently from a real return under heavy tails. This script measures the
thing the name implies: log(session_close / session_open) per session, per
day - can be negative, has a genuine two-sided shape. Use THIS version, not
v2a's range-ratio version, for anything downstream that assumes a
return-distribution shape (e.g. stop-loss/take-profit sizing, VaR-style
risk assumptions in Phase 4/5) - v2a answers a related but different
question (does the SIZE of the daily range shift), not whether the
direction/shape of the return itself is stable.

Same corrections as v2a: block-permutation significance
(distribution_stability_common.py), DST-aware London/NY sessions, event-day
flagging, CSV output. Session open/close use the actual open of the first
bar and close of the last bar within each session window (not prior day's
close), so this is a genuine intra-session return, not a full-day one.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\return_distribution_stability.py
Output: console tables + return_distribution_stability_results.csv
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import range_prediction_v3_baselines as R
from distribution_shape_stability_v2a import get_event_days, run_session
from distribution_stability_common import MIN_N

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"


def session_returns_fixed(con, start_h, end_h):
    s, e = start_h * 60, end_h * 60
    df = con.execute(f"""
        SELECT date_trunc('day', minute_ts) AS day,
               arg_min(open, minute_ts) FILTER (WHERE minute_of_day >= {s} AND minute_of_day < {e}) AS s_open,
               arg_max(close, minute_ts) FILTER (WHERE minute_of_day >= {s} AND minute_of_day < {e}) AS s_close
        FROM minute_bars_ohlc
        WHERE NOT (minute_of_day >= {R.CLOSURE_START_MIN} AND minute_of_day < {R.CLOSURE_END_MIN})
        GROUP BY day HAVING count(*) FILTER (WHERE minute_of_day >= {s} AND minute_of_day < {e}) > 30
    """).fetchdf()
    df["day"] = R._to_naive_utc_day(df["day"])
    df["ratio"] = np.log(df["s_close"] / df["s_open"])   # genuine signed return; kept as "ratio" for run_session()
    return df[["day", "ratio"]]


def session_returns_dst(con, start_h, end_h, tz):
    s, e = start_h * 60, end_h * 60
    df = con.execute(f"""
        WITH b AS (
            SELECT minute_ts, open, close, minute_of_day,
                   (extract(hour FROM lt) * 60 + extract(minute FROM lt)) AS lmin
            FROM (SELECT *, timezone('{tz}', minute_ts::TIMESTAMPTZ) AS lt FROM minute_bars_ohlc)
        )
        SELECT date_trunc('day', minute_ts) AS day,
               arg_min(open, minute_ts) FILTER (WHERE lmin >= {s} AND lmin < {e}) AS s_open,
               arg_max(close, minute_ts) FILTER (WHERE lmin >= {s} AND lmin < {e}) AS s_close
        FROM b
        WHERE NOT (minute_of_day >= {R.CLOSURE_START_MIN} AND minute_of_day < {R.CLOSURE_END_MIN})
        GROUP BY day HAVING count(*) FILTER (WHERE lmin >= {s} AND lmin < {e}) > 30
    """).fetchdf()
    df["day"] = R._to_naive_utc_day(df["day"])
    df["ratio"] = np.log(df["s_close"] / df["s_open"])
    return df[["day", "ratio"]]


def main(con=None):
    if con is None:
        con = duckdb.connect(ANALYTICS_DB, read_only=True)
    con.execute("SET TimeZone='UTC'")
    event_days = get_event_days(con)
    print(f"whitelisted high-impact event days found: {len(event_days)}")

    jobs = [("asian", "fixed_utc", session_returns_fixed(con, *R.FIXED_SESSIONS["asian"]))]
    for name in ["london", "ny"]:
        jobs.append((name, "fixed_utc", session_returns_fixed(con, *R.FIXED_SESSIONS[name])))
        sh, eh, tz = R.DST_SESSIONS[name]
        jobs.append((name, "dst_aware", session_returns_dst(con, sh, eh, tz)))

    rows_out = []
    for name, mode, df in jobs:
        run_session(df, event_days, name, mode, rows_out)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "return_distribution_stability_results.csv")
    pd.DataFrame(rows_out).to_csv(out, index=False)
    print(f"\nSaved: {out}")
    print(f"\nMIN_N for any test = {MIN_N}; kurtosis flagged low-confidence below 60 observations per side.")
    print("This is the SIGNED return version - compare its skew sign/direction against v2a's range-ratio")
    print("version rather than treating them as two measurements of the same thing.")


if __name__ == "__main__":
    main()