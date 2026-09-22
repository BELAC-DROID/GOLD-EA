"""
Trim dxy_m1_ohlc down to its genuinely usable intraday range. Confirmed
via direct inspection: every day from 2019-03-01 through 2021-07-15 has
exactly 1 bar (a daily-close placeholder, not real M1 data); real
minute-by-minute coverage starts cleanly at 2021-07-19.
"""

import duckdb

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
con = duckdb.connect(ANALYTICS_DB)

before = con.execute("SELECT count(*) FROM dxy_m1_ohlc").fetchone()[0]

con.execute("""
    DELETE FROM dxy_m1_ohlc WHERE minute_ts < '2021-07-19'
""")

after, min_ts, max_ts = con.execute(
    "SELECT count(*), min(minute_ts), max(minute_ts) FROM dxy_m1_ohlc"
).fetchone()

print(f"Rows before trim: {before:,}")
print(f"Rows removed (placeholder daily bars): {before - after:,}")
print(f"Rows after trim: {after:,}")
print(f"New usable range: {min_ts} to {max_ts}")

con.close()