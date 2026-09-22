"""
Inspect analytics.duckdb's actual table names and schemas before rebuilding
minute_bars_ohlc and its derived timeframes - avoids guessing table names
for M5/M15/M30/H1/H4/D1 and accidentally creating duplicates alongside
whatever build_minute_bars_ohlc.py originally created.
"""

import duckdb

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

con = duckdb.connect(ANALYTICS_DB)

print("=== Tables in analytics.duckdb ===")
tables = con.execute("SHOW TABLES").fetchdf()
print(tables)

print("\n=== Row counts and date ranges per table ===")
for name in tables["name"]:
    try:
        count = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        cols = con.execute(f"DESCRIBE {name}").fetchdf()["column_name"].tolist()
        ts_col = "minute_ts" if "minute_ts" in cols else (
            "day" if "day" in cols else None
        )
        if ts_col:
            min_ts, max_ts = con.execute(
                f"SELECT min({ts_col}), max({ts_col}) FROM {name}"
            ).fetchone()
            print(f"{name}: {count:,} rows, columns={cols}, range=({min_ts} to {max_ts})")
        else:
            print(f"{name}: {count:,} rows, columns={cols} (no obvious timestamp column)")
    except Exception as e:
        print(f"{name}: error inspecting - {e}")
    