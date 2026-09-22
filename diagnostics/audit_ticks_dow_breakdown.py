"""
Follow-up: classify every thin day by day-of-week to confirm the thin-day
pattern is just Sundays/holidays, not hidden weekday gaps.
"""

import duckdb

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
con = duckdb.connect()
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")

daily_counts = con.execute("""
    SELECT date_trunc('day', to_timestamp(timestamp_utc_ms / 1000.0)) AS day, count(*) AS n_ticks
    FROM gold.ticks WHERE source = 'dukascopy'
    GROUP BY day
""").fetchdf()

median_n = daily_counts["n_ticks"].median()
thin = daily_counts[daily_counts["n_ticks"] < median_n * 0.1].copy()
thin["dow"] = thin["day"].dt.day_name()

print(f"Total thin days: {len(thin)}")
print("\nBreakdown by day of week:")
print(thin["dow"].value_counts())

non_sunday_thin = thin[thin["dow"] != "Sunday"]
print(f"\nThin days that are NOT Sunday ({len(non_sunday_thin)}) - these need individual inspection:")
print(non_sunday_thin.sort_values("day").to_string())