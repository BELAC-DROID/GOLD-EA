import duckdb

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
CLOSURE_START_MIN = 20 * 60 + 58   # 1258
CLOSURE_END_MIN = 22 * 60          # 1320

con = duckdb.connect()
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")

con.execute("""
    CREATE OR REPLACE TEMP TABLE minute_bars AS
    SELECT
        date_trunc('minute', to_timestamp(timestamp_utc_ms / 1000.0)) AS minute_ts,
        (extract(hour FROM to_timestamp(timestamp_utc_ms / 1000.0)) * 60
         + extract(minute FROM to_timestamp(timestamp_utc_ms / 1000.0))) AS minute_of_day,
        min((bid + ask) / 2.0) AS low,
        max((bid + ask) / 2.0) AS high
    FROM gold.ticks
    WHERE source = 'dukascopy'
    GROUP BY 1, 2
""")

# Step 1: does the exclusion condition itself correctly drop rows?
print("Row count BEFORE exclusion, minute_of_day in [1258,1320):")
print(con.execute("""
    SELECT count(*) FROM minute_bars
    WHERE minute_of_day >= 1258 AND minute_of_day < 1320
""").fetchone())

print("Row count AFTER applying NOT(...) exclusion, same range:")
print(con.execute("""
    SELECT count(*) FROM minute_bars
    WHERE NOT (minute_of_day >= 1258 AND minute_of_day < 1320)
      AND minute_of_day >= 1258 AND minute_of_day < 1320
""").fetchone())

# Step 2: reproduce the exact bucketing CTE and inspect bucket 1260 directly
print("\nBucket_start values produced for minute_of_day 1258-1274, post-exclusion:")
print(con.execute("""
    SELECT (minute_of_day / 15)::INT * 15 AS bucket_start, minute_of_day, count(*)
    FROM minute_bars
    WHERE NOT (minute_of_day >= 1258 AND minute_of_day < 1320)
      AND minute_of_day BETWEEN 1245 AND 1280
    GROUP BY 1, 2 ORDER BY 2
""").fetchdf())