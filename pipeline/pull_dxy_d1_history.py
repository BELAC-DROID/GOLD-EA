"""
One-time loader: pull DXYm's genuine D1 (daily) history from MT5 into
its own table, separate from dxy_m1_ohlc.

Needed because pull_dxy_history.py only ever pulled M1 data, and the
pre-2021-07-19 M1 rows (later confirmed to be daily-value placeholders,
not real intraday data) were deleted by trim_dxy_placeholder_rows.py -
which means daily DXY values for 2019-03-01 through 2021-07-18 are not
stored anywhere unless pulled fresh here, directly from D1.
"""

import MetaTrader5 as mt5
import duckdb
import pandas as pd
from datetime import datetime, timezone

SYMBOL = "DXYm"
ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
START = datetime(2019, 3, 1, tzinfo=timezone.utc)
END = datetime.now(timezone.utc)

if not mt5.initialize():
    print("MT5 initialize() failed:", mt5.last_error())
    raise SystemExit

rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_D1, START, END)
mt5.shutdown()

if rates is None or len(rates) == 0:
    print("No D1 data returned - stopping.")
    raise SystemExit

df = pd.DataFrame(rates)
df["day"] = pd.to_datetime(df["time"], unit="s", utc=True)
df = df.drop_duplicates(subset="day").sort_values("day")

print(f"D1 bars pulled: {len(df):,}")
print(f"Range: {df['day'].min()} to {df['day'].max()}")

con = duckdb.connect(ANALYTICS_DB)
con.execute("""
    CREATE OR REPLACE TABLE dxy_d1_ohlc AS
    SELECT day, open, high, low, close FROM df
""")
count, min_d, max_d = con.execute(
    "SELECT count(*), min(day), max(day) FROM dxy_d1_ohlc"
).fetchone()
print(f"\nSaved to analytics.duckdb as 'dxy_d1_ohlc': {count:,} rows, {min_d} to {max_d}")
con.close()