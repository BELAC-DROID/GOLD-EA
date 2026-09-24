"""
2026 holdout, step 1: build OHLC bars from real Exness ticks for the period
Test 1 never touched.

WHY THIS EXISTS: minute_bars_ohlc (built from Dukascopy) stops at
2025-12-31. Exness_live ticks (source='exness_live' in gold_data.db) cover
2026-01-01 to ~now on a DIFFERENT, real (not interbank-reference) feed. This
builds the same bar tables the existing scripts already expect
(minute_bars_ohlc, bars_h1, bars_h4, bars_m30, bars_d1), for 2026 only, in a
SEPARATE file - analytics_2026_holdout.duckdb - so nothing touches the
production analytics.duckdb, and every existing v3/v2 script can run
against this file completely unmodified (they all accept an optional
`con` parameter and otherwise use these exact table names).

IMPORTANT ASSUMPTION, NOT YET CONFIRMED: bar price = mid-price
((bid+ask)/2). I do not know for certain what price convention the
ORIGINAL Dukascopy-derived minute_bars_ohlc uses (bid-only is also a common
convention for OHLC bars). If it turns out to be bid-only, these 2026 bars
carry a small, consistent half-spread offset relative to the original
table - probably immaterial for skew/regime/persistence-style tests, but
verify before treating any absolute-magnitude comparison (e.g. exact MAE
values) between 2019-2025 and 2026 as precise. Confirm by checking
whichever script originally built minute_bars_ohlc from Dukascopy ticks.

PERFORMANCE: builds via ONE aggregating SQL pass over the ticks table
(GROUP BY minute), not per-row Python - this is the same "one scan, not
many" lesson from spread_model_validation.py's earlier 3-hour hang.
Expect this single pass to take roughly as long as loading exness_live did
before (~8-13 minutes), since it still has to read the same rows once.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\build_2026_holdout_bars.py
"""

import os
import sys
import time

import duckdb

GOLD_DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
ORIG_ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
HOLDOUT_DB_PATH = r"C:\Users\opc\gold_ea\data\analytics_2026_holdout.duckdb"
SOURCE = "exness_live"


def build_minute_bars(con):
    print("attaching gold_data.db (sqlite) and building minute_bars_ohlc from "
          f"ticks WHERE source='{SOURCE}' - one aggregating pass, ~8-13 min...")
    t0 = time.time()
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{GOLD_DB_PATH}' AS gold (TYPE sqlite);")
    con.execute(f"""
        CREATE OR REPLACE TABLE minute_bars_ohlc AS
        WITH priced AS (
            SELECT to_timestamp(timestamp_utc_ms / 1000.0) AS ts,
                   (bid + ask) / 2.0 AS price   -- ASSUMPTION: mid-price, see module docstring
            FROM gold.ticks
            WHERE source = '{SOURCE}'
        ),
        bucketed AS (
            SELECT date_trunc('minute', ts) AS minute_ts, ts, price,
                   row_number() OVER (PARTITION BY date_trunc('minute', ts) ORDER BY ts) AS rn_asc,
                   row_number() OVER (PARTITION BY date_trunc('minute', ts) ORDER BY ts DESC) AS rn_desc
            FROM priced
        )
        SELECT minute_ts,
               (extract(hour FROM minute_ts) * 60 + extract(minute FROM minute_ts))::INTEGER AS minute_of_day,
               max(price) FILTER (WHERE rn_asc = 1) AS open,
               max(price) AS high,
               min(price) AS low,
               max(price) FILTER (WHERE rn_desc = 1) AS close
        FROM bucketed
        GROUP BY minute_ts
        ORDER BY minute_ts
    """)
    n = con.execute("SELECT count(*) FROM minute_bars_ohlc").fetchone()[0]
    lo, hi = con.execute("SELECT min(minute_ts), max(minute_ts) FROM minute_bars_ohlc").fetchone()
    print(f"  built {n:,} minute bars, {lo} -> {hi}, in {time.time() - t0:.0f}s")


def build_resampled(con, name, rule):
    con.execute(f"""
        CREATE OR REPLACE TABLE {name} AS
        WITH bucketed AS (
            SELECT time_bucket(INTERVAL '{rule}', minute_ts) AS bar_ts, minute_ts, open, high, low, close,
                   row_number() OVER (PARTITION BY time_bucket(INTERVAL '{rule}', minute_ts) ORDER BY minute_ts) AS rn_asc,
                   row_number() OVER (PARTITION BY time_bucket(INTERVAL '{rule}', minute_ts) ORDER BY minute_ts DESC) AS rn_desc
            FROM minute_bars_ohlc
        )
        SELECT bar_ts,
               max(open) FILTER (WHERE rn_asc = 1) AS open,
               max(high) AS high,
               min(low) AS low,
               max(close) FILTER (WHERE rn_desc = 1) AS close
        FROM bucketed
        GROUP BY bar_ts
        ORDER BY bar_ts
    """)
    n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    print(f"  {name}: {n:,} bars")


def build_dxy_view(con):
    """K/L need dxy_m1_ohlc - it already covers 2026 in the ORIGINAL analytics.duckdb
    (confirmed 2026-09-21: dxy_m1_ohlc runs to ~2026-09-21). Attach it read-only and
    materialize just the 2026 slice here, rather than copying the whole table."""
    print("attaching original analytics.duckdb (read-only) for the DXY 2026 slice...")
    con.execute(f"ATTACH '{ORIG_ANALYTICS_DB}' AS orig (READ_ONLY);")
    con.execute("""
        CREATE OR REPLACE TABLE dxy_m1_ohlc AS
        SELECT * FROM orig.dxy_m1_ohlc WHERE minute_ts >= '2026-01-01'
    """)
    n = con.execute("SELECT count(*) FROM dxy_m1_ohlc").fetchone()[0]
    print(f"  dxy_m1_ohlc (2026 slice): {n:,} bars")


def main():
    if os.path.exists(HOLDOUT_DB_PATH):
        print(f"NOTE: {HOLDOUT_DB_PATH} already exists and will be overwritten (tables use CREATE OR REPLACE).")
    con = duckdb.connect(HOLDOUT_DB_PATH)
    con.execute("SET TimeZone='UTC'")

    build_minute_bars(con)
    print("\nbuilding H4/H1/M30/D1 from minute_bars_ohlc...")
    build_resampled(con, "bars_h4", "4 hours")
    build_resampled(con, "bars_h1", "1 hour")
    build_resampled(con, "bars_m30", "30 minutes")
    build_resampled(con, "bars_d1", "1 day")

    build_dxy_view(con)

    con.close()
    print(f"\nDone. Holdout database: {HOLDOUT_DB_PATH}")
    print("Next: run_2026_holdout.py, which points the existing v3/v2 scripts at this file.")


if __name__ == "__main__":
    main()