"""
Load the 2025 Dukascopy tick CSV (from dukascopy-node) into the ticks
table with source='dukascopy'.

Auto-detects:
- whether a header row is present
- whether the file has 3 columns (timestamp, askPrice, bidPrice) or
  5 (with askVolume, bidVolume added - volumes are ignored on insert
  since the ticks table doesn't store them)

Only deletes existing 2025 rows before inserting (2019-2024 stays
untouched) - safe to rerun.
"""

import sqlite3
import pandas as pd
import time
import csv

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
CSV_PATH = r"C:\Users\opc\gold_ea\downloads\xauusd-tick-2025-01-01-2026-01-01.csv"  # <-- update this
SYMBOL = "XAUUSD"
CHUNK_SIZE = 500_000

YEAR_START_MS = 1735689600000  # 2025-01-01 00:00:00 UTC
YEAR_END_MS = 1767225600000    # 2026-01-01 00:00:00 UTC

# --- Step 1: detect shape before doing anything else ---
with open(CSV_PATH, "r") as f:
    first_line = f.readline().strip()
    second_line = f.readline().strip()

first_fields = first_line.split(",")
n_cols = len(first_fields)
has_header = not first_fields[0].replace(".", "").isdigit()  # header starts with a word, data starts with a number

print("=== Detected file shape ===")
print(f"First line : {first_line}")
print(f"Second line: {second_line}")
print(f"Columns detected: {n_cols}")
print(f"Header row detected: {has_header}")

if n_cols == 3:
    col_names = ["timestamp_utc_ms", "ask", "bid"]
elif n_cols == 5:
    col_names = ["timestamp_utc_ms", "ask", "bid", "ask_volume", "bid_volume"]
else:
    raise ValueError(f"Unexpected column count ({n_cols}) - stop and check the file manually before proceeding")

print(f"Column mapping assumed: {col_names}")
print("\nIf the above looks wrong, Ctrl+C now before it touches the database.\n")
time.sleep(5)  # last chance to bail before writing

# --- Step 2: load ---
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute(
    "DELETE FROM ticks WHERE source = 'dukascopy' AND timestamp_utc_ms >= ? AND timestamp_utc_ms < ?",
    (YEAR_START_MS, YEAR_END_MS),
)
conn.commit()
print(f"Cleared any existing 2025 dukascopy rows: {cursor.rowcount:,}")

start = time.time()
total_rows = 0
for chunk in pd.read_csv(
    CSV_PATH,
    header=0 if has_header else None,
    names=col_names,
    usecols=["timestamp_utc_ms", "ask", "bid"],  # ignore volume columns if present
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
print(f"\nDone. Total 2025 rows inserted: {total_rows:,}")