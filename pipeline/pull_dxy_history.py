"""
One-time loader: pull DXYm's full M1 history from MT5 and store it into
analytics.duckdb, so Metrics K (correlation-regime) and L (lead-lag)
can join against it directly rather than re-querying MT5 live.

Confirmed via check_mt5_dxy_availability.py: DXYm has D1 history back to
2019-03-01 and M1 intraday data. This pulls M1 (the finer of the two) -
D1 and other timeframes can be derived from M1 later the same way
minute_bars_ohlc's derived tables were built, keeping one source of
truth rather than pulling multiple resolutions separately.
"""

import MetaTrader5 as mt5
import duckdb
import pandas as pd
from datetime import datetime, timezone

SYMBOL = "DXYm"
ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
START = datetime(2019, 3, 1, tzinfo=timezone.utc)
END = datetime.now(timezone.utc)
CHUNK_DAYS = 90  # MT5 can be unreliable pulling huge multi-year ranges in one call

if not mt5.initialize():
    print("MT5 initialize() failed:", mt5.last_error())
    raise SystemExit

all_rates = []
cur_start = START
while cur_start < END:
    cur_end = min(cur_start + pd.Timedelta(days=CHUNK_DAYS), END)
    rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, cur_start, cur_end)
    if rates is not None and len(rates) > 0:
        all_rates.append(pd.DataFrame(rates))
        print(f"  {cur_start.date()} to {cur_end.date()}: {len(rates)} bars")
    else:
        print(f"  {cur_start.date()} to {cur_end.date()}: no data")
    cur_start = cur_end

mt5.shutdown()

if not all_rates:
    print("No data pulled at all - stopping.")
    raise SystemExit

df = pd.concat(all_rates, ignore_index=True)
df["minute_ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
df = df.drop_duplicates(subset="minute_ts").sort_values("minute_ts")

print(f"\nTotal M1 bars pulled: {len(df):,}")
print(f"Range: {df['minute_ts'].min()} to {df['minute_ts'].max()}")

con = duckdb.connect(ANALYTICS_DB)
con.execute("""
    CREATE OR REPLACE TABLE dxy_m1_ohlc AS
    SELECT minute_ts, open, high, low, close
    FROM df
""")

count, min_ts, max_ts = con.execute(
    "SELECT count(*), min(minute_ts), max(minute_ts) FROM dxy_m1_ohlc"
).fetchone()
print(f"\nSaved to analytics.duckdb as 'dxy_m1_ohlc': {count:,} rows, {min_ts} to {max_ts}")
con.close()
