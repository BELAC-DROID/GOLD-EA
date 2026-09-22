"""
Rebuild minute_bars_ohlc (M1) from raw Dukascopy ticks in gold_data.db,
picking up the 2025 (and later) data that was loaded after this table
was originally built, then rebuild all derived timeframes from it.

Dukascopy-only, matching the project's established train-on-Dukascopy
decision - confirmed via check_analytics_schema.py that minute_bars_ohlc
previously ended 2024-12-30, well before any exness_live data exists.

Bucket boundaries use floor()-based epoch-second arithmetic throughout,
not DuckDB's (x/n)::INT rounding cast - that rounding-vs-truncation bug
already cost a full debugging round in baseline_profiler.py, so this
avoids repeating it here for the derived timeframes.

open/close are computed via arg_min/arg_max ordered by timestamp - this
matches the existing table's schema (which has open/close columns) but
is a reconstruction, not a confirmed match to however the table was
originally built. Worth a quick spot-check against known bars after
this runs.
"""

import duckdb
import time

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

# (table_name, bucket_seconds or None for calendar-day)
DERIVED_TIMEFRAMES = [
    ("bars_m5", 5 * 60),
    ("bars_m15", 15 * 60),
    ("bars_m30", 30 * 60),
    ("bars_h1", 60 * 60),
    ("bars_h4", 4 * 60 * 60),
    ("bars_d1", None),  # calendar day, handled separately
]

con = duckdb.connect(ANALYTICS_DB)
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")

start = time.time()

print("Rebuilding minute_bars_ohlc (M1) from raw Dukascopy ticks...")
con.execute("""
    CREATE OR REPLACE TABLE minute_bars_ohlc AS
    SELECT
        date_trunc('minute', to_timestamp(timestamp_utc_ms / 1000.0)) AS minute_ts,
        (extract(hour FROM to_timestamp(timestamp_utc_ms / 1000.0)) * 60
         + extract(minute FROM to_timestamp(timestamp_utc_ms / 1000.0)))::INT AS minute_of_day,
        arg_min((bid + ask) / 2.0, timestamp_utc_ms) AS open,
        max((bid + ask) / 2.0) AS high,
        min((bid + ask) / 2.0) AS low,
        arg_max((bid + ask) / 2.0, timestamp_utc_ms) AS close
    FROM gold.ticks
    WHERE source = 'dukascopy'
    GROUP BY 1, 2
    ORDER BY 1
""")

m1_count, m1_min, m1_max = con.execute(
    "SELECT count(*), min(minute_ts), max(minute_ts) FROM minute_bars_ohlc"
).fetchone()
print(f"  minute_bars_ohlc: {m1_count:,} rows, {m1_min} to {m1_max} "
      f"({time.time() - start:.1f}s elapsed)\n")

for table_name, bucket_seconds in DERIVED_TIMEFRAMES:
    print(f"Rebuilding {table_name}...")
    if bucket_seconds is None:
        bucket_expr = "date_trunc('day', minute_ts)"
    else:
        bucket_expr = (
            f"to_timestamp(floor(epoch(minute_ts) / {bucket_seconds}.0)::BIGINT * {bucket_seconds})"
        )

    con.execute(f"""
        CREATE OR REPLACE TABLE {table_name} AS
        WITH bucketed AS (
            SELECT {bucket_expr} AS bar_ts, minute_ts, open, high, low, close
            FROM minute_bars_ohlc
        )
        SELECT
            bar_ts,
            arg_min(open, minute_ts) AS open,
            max(high) AS high,
            min(low) AS low,
            arg_max(close, minute_ts) AS close
        FROM bucketed
        GROUP BY bar_ts
        ORDER BY bar_ts
    """)

    count, min_ts, max_ts = con.execute(
        f"SELECT count(*), min(bar_ts), max(bar_ts) FROM {table_name}"
    ).fetchone()
    print(f"  {table_name}: {count:,} rows, {min_ts} to {max_ts} "
          f"({time.time() - start:.1f}s elapsed)\n")

print(f"All tables rebuilt. Total time: {time.time() - start:.1f}s")