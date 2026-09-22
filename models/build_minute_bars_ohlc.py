"""
Phase 2, Piece 2 prep: build persistent OHLC bars across timeframes.

M1 (minute_bars_ohlc) is built directly from raw ticks - the one
expensive scan. Everything else (M5/M15/M30/H1/H4/D1) is derived from
M1 via cheap aggregation, not a second scan of the 282M raw ticks.
"""

import duckdb
import time

SOURCE_DB = r"C:\Users\opc\gold_ea\data\gold_data.db"
ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

start = time.time()
con = duckdb.connect(ANALYTICS_DB)
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{SOURCE_DB}' AS gold (TYPE sqlite);")

print("Building M1 OHLC bars from raw ticks (the expensive step)...")
con.execute("""
    CREATE OR REPLACE TABLE minute_bars_ohlc AS
    WITH ticks_mid AS (
        SELECT
            date_trunc('minute', to_timestamp(timestamp_utc_ms / 1000.0)) AS minute_ts,
            timestamp_utc_ms,
            (bid + ask) / 2.0 AS mid
        FROM gold.ticks
        WHERE source = 'dukascopy'
    ),
    ranked AS (
        SELECT minute_ts, mid,
               row_number() OVER (PARTITION BY minute_ts ORDER BY timestamp_utc_ms) AS rn_first,
               row_number() OVER (PARTITION BY minute_ts ORDER BY timestamp_utc_ms DESC) AS rn_last
        FROM ticks_mid
    )
    SELECT
        minute_ts,
        (extract(hour FROM minute_ts) * 60 + extract(minute FROM minute_ts))::INT AS minute_of_day,
        max(CASE WHEN rn_first = 1 THEN mid END) AS open,
        max(mid) AS high,
        min(mid) AS low,
        max(CASE WHEN rn_last = 1 THEN mid END) AS close
    FROM ranked
    GROUP BY minute_ts
""")
n_m1 = con.execute("SELECT count(*) FROM minute_bars_ohlc").fetchone()[0]
print(f"  M1 done: {n_m1:,} bars ({time.time() - start:.1f}s elapsed)")

# Derive higher timeframes from M1 - cheap, no raw-tick rescan
TIMEFRAMES = {
    "m5":  "5 minutes",
    "m15": "15 minutes",
    "m30": "30 minutes",
    "h1":  "1 hour",
    "h4":  "4 hours",
    "d1":  "1 day",
}

for tf_name, interval in TIMEFRAMES.items():
    t0 = time.time()
    con.execute(f"""
        CREATE OR REPLACE TABLE bars_{tf_name} AS
        WITH bucketed AS (
            SELECT
                time_bucket(INTERVAL '{interval}', minute_ts) AS bar_ts,
                minute_ts, open, high, low, close,
                row_number() OVER (PARTITION BY time_bucket(INTERVAL '{interval}', minute_ts) ORDER BY minute_ts) AS rn_first,
                row_number() OVER (PARTITION BY time_bucket(INTERVAL '{interval}', minute_ts) ORDER BY minute_ts DESC) AS rn_last
            FROM minute_bars_ohlc
        )
        SELECT
            bar_ts,
            max(CASE WHEN rn_first = 1 THEN open END) AS open,
            max(high) AS high,
            min(low) AS low,
            max(CASE WHEN rn_last = 1 THEN close END) AS close
        FROM bucketed
        GROUP BY bar_ts
        ORDER BY bar_ts
    """)
    n = con.execute(f"SELECT count(*) FROM bars_{tf_name}").fetchone()[0]
    print(f"  {tf_name.upper()} done: {n:,} bars ({time.time() - t0:.1f}s)")

print(f"\nAll timeframes saved to {ANALYTICS_DB}")
print(f"Total elapsed: {time.time() - start:.1f}s")
con.close()