"""
Phase 3, Test 1, Metric H (calendar-proximity half): Anomaly-Flagging Precision

Flag: does a whitelisted high-impact event (imported directly from
spread_model.py - not duplicated) fall within a given session's UTC
window on a given day?

Ground truth: same session-level "actual_high" volatility regime label
used in the opening-range half and Metric C (top 20th percentile of a
trailing 100-day range-ratio window) - so both halves of Metric H are
directly comparable on the same ground truth.

Scored as precision vs. the unconditional base rate, same structure as
the opening-range half.
"""

import sys
import duckdb
import numpy as np

sys.path.insert(0, r"C:\Users\opc\gold_ea\models")
from spread_model import EVENT_NAME_WHITELIST, EVENT_CURRENCIES

from walk_forward_matrix import COMBOS, generate_splits

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
SESSIONS = {"asian": (0, 8), "london": (8, 16), "ny": (13, 21)}
FULL_DAY_LOOKBACK = 100
FULL_DAY_HIGH_PCTL = 80

con = duckdb.connect(ANALYTICS_DB)
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")


def daily_ratio(start_h, end_h):
    start_min, end_min = start_h * 60, end_h * 60
    return con.execute(f"""
        WITH full_bars AS (
            SELECT date_trunc('day', minute_ts) AS day, high, low
            FROM minute_bars_ohlc
            WHERE minute_of_day >= {start_min} AND minute_of_day < {end_min}
              AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        ),
        full_range AS (
            SELECT day, (max(high) - min(low)) AS day_range
            FROM full_bars GROUP BY day HAVING count(*) > 30
        ),
        daily_close AS (
            SELECT date_trunc('day', minute_ts) AS day, arg_max(close, minute_ts) AS day_close
            FROM minute_bars_ohlc GROUP BY day
        ),
        with_prior AS (
            SELECT day, day_close, LAG(day_close) OVER (ORDER BY day) AS prior_close
            FROM daily_close
        )
        SELECT f.day, f.day_range / p.prior_close AS day_ratio
        FROM full_range f JOIN with_prior p ON p.day = f.day
        WHERE p.prior_close IS NOT NULL
        ORDER BY f.day
    """).fetchdf()


def label_actual_high(df, lookback=FULL_DAY_LOOKBACK):
    ratios = df["day_ratio"].values
    actual_high = [None] * len(ratios)
    for i in range(lookback, len(ratios)):
        window = ratios[i - lookback:i]
        hi = np.percentile(window, FULL_DAY_HIGH_PCTL)
        actual_high[i] = ratios[i] > hi
    df = df.copy()
    df["actual_high"] = actual_high
    return df.dropna(subset=["actual_high"])


def event_days_for_session(start_h, end_h):
    """Days where a whitelisted event's UTC time falls inside this session's window."""
    start_min, end_min = start_h * 60, end_h * 60
    name_ph = ",".join("?" for _ in EVENT_NAME_WHITELIST)
    curr_ph = ",".join("?" for _ in EVENT_CURRENCIES)
    rows = con.execute(f"""
        SELECT DISTINCT date_trunc('day', to_timestamp(timestamp_utc_ms/1000.0)) AS day
        FROM gold.calendar_events
        WHERE event_name IN ({name_ph}) AND currency IN ({curr_ph})
          AND (extract(hour FROM to_timestamp(timestamp_utc_ms/1000.0)) * 60
               + extract(minute FROM to_timestamp(timestamp_utc_ms/1000.0))) >= {start_min}
          AND (extract(hour FROM to_timestamp(timestamp_utc_ms/1000.0)) * 60
               + extract(minute FROM to_timestamp(timestamp_utc_ms/1000.0))) < {end_min}
    """, (*EVENT_NAME_WHITELIST, *EVENT_CURRENCIES)).fetchdf()
    return set(rows["day"])


for name, (start_h, end_h) in SESSIONS.items():
    df = label_actual_high(daily_ratio(start_h, end_h))
    event_days = event_days_for_session(start_h, end_h)
    df["flagged"] = df["day"].isin(event_days)

    print(f"\n{'='*70}\nSession: {name}  ({len(event_days)} event-days in this session's window)\n{'='*70}")
    for combo in COMBOS:
        splits = generate_splits(combo)
        all_flagged_actual, all_base_actual = [], []
        for s in splits:
            test = df[(df["day"] >= s["test_start"]) & (df["day"] <= s["test_end"])]
            if len(test) < 10:
                continue
            all_base_actual.extend(test["actual_high"].tolist())
            all_flagged_actual.extend(test[test["flagged"]]["actual_high"].tolist())
        if not all_flagged_actual:
            print(f"  {combo['name']:25s}  no flagged days in test period")
            continue
        precision = np.mean(all_flagged_actual)
        base_rate = np.mean(all_base_actual)
        flag = "BEATS base rate" if precision > base_rate else "does NOT beat base rate"
        print(f"  {combo['name']:25s}  n_flagged={len(all_flagged_actual):4d}  "
              f"precision={precision:.3f}  base_rate={base_rate:.3f}  -> {flag}")