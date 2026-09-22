"""
Data quality audit for the ticks table: gaps and duplicates, per source.
Run this BEFORE adding the 2025 Dukascopy data, so any problems found
are attributable to the existing load, not the new one.
"""

import duckdb
import sys

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
SOURCE = sys.argv[1] if len(sys.argv) > 1 else "dukascopy"  # run once per source

con = duckdb.connect()
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")

print(f"=== Auditing source = '{SOURCE}' ===\n")

# 1. Exact duplicate rows (same symbol, timestamp, source - would double-count in bars)
dupes = con.execute(f"""
    SELECT timestamp_utc_ms, count(*) AS n
    FROM gold.ticks
    WHERE source = '{SOURCE}'
    GROUP BY timestamp_utc_ms
    HAVING count(*) > 1
""").fetchall()
print(f"Duplicate timestamps: {len(dupes):,}")
if dupes:
    print("  Sample:", dupes[:5])

# 2. Daily tick-count profile - spot missing/thin days at a glance
daily_counts = con.execute(f"""
    SELECT date_trunc('day', to_timestamp(timestamp_utc_ms / 1000.0)) AS day, count(*) AS n_ticks
    FROM gold.ticks
    WHERE source = '{SOURCE}'
    GROUP BY day
    ORDER BY day
""").fetchdf()

print(f"\nTotal days with any data: {len(daily_counts):,}")
print(f"Tick count per day - min={daily_counts['n_ticks'].min():,}, "
      f"median={daily_counts['n_ticks'].median():,.0f}, max={daily_counts['n_ticks'].max():,}")

# Flag days far below the median as likely thin/broken, not just quiet
median_n = daily_counts["n_ticks"].median()
thin_days = daily_counts[daily_counts["n_ticks"] < median_n * 0.1]
print(f"\nDays with <10% of median tick count ({len(thin_days)} days) - inspect these:")
print(thin_days.head(20))

# 3. Calendar gap check - are there whole weekdays missing entirely?
full_range = con.execute(f"""
    SELECT min(date_trunc('day', to_timestamp(timestamp_utc_ms/1000.0))),
           max(date_trunc('day', to_timestamp(timestamp_utc_ms/1000.0)))
    FROM gold.ticks WHERE source = '{SOURCE}'
""").fetchone()
print(f"\nData spans {full_range[0].date()} to {full_range[1].date()}")

expected_weekdays = con.execute(f"""
    SELECT count(*) FROM range(TIMESTAMP '{full_range[0]}', TIMESTAMP '{full_range[1]}', INTERVAL '1 day') t(d)
    WHERE dayofweek(d) NOT IN (0, 6)
""").fetchone()[0]
print(f"Expected weekdays in range: {expected_weekdays:,}  |  Actual days with data: {len(daily_counts):,}")
print(f"Missing weekdays: {expected_weekdays - len(daily_counts):,} (some gap is normal for holidays)")