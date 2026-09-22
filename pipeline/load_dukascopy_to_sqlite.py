import sqlite3
import pandas as pd
import time

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
CSV_PATH = r"C:\Users\opc\xauusd-history-full\xauusd-tick-2019-01-01-2024-12-31.csv"
SYMBOL = "XAUUSD"
CHUNK_SIZE = 500_000

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Safety: wipe any previous partial/duplicate dukascopy import before
# starting - there's no UNIQUE constraint on the ticks table, so a
# rerun without this line would double-insert everything again.
cursor.execute("DELETE FROM ticks WHERE source = 'dukascopy'")
conn.commit()

start = time.time()
total_rows = 0

for chunk in pd.read_csv(
    CSV_PATH,
    header=0,  # the Dukascopy CSVs have a header row: timestamp,askPrice,bidPrice
    names=["timestamp_utc_ms", "ask", "bid"],
    chunksize=CHUNK_SIZE,
):
    rows = [
        (SYMBOL, int(r.timestamp_utc_ms), float(r.bid), float(r.ask), "dukascopy")
        for r in chunk.itertuples(index=False)
    ]
    cursor.executemany(
        "INSERT INTO ticks (symbol, timestamp_utc_ms, bid, ask, source) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    total_rows += len(rows)
    print(f"Inserted {total_rows:,} rows so far ({time.time() - start:.1f}s elapsed)")

conn.close()
print(f"Done. Total rows inserted: {total_rows:,}")