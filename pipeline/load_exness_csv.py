"""
Load an Exness tick export (tab-separated: DATE TIME BID ASK LAST VOLUME FLAGS)
into the ticks table with source='exness_live'.

Fix applied: the timestamp conversion previously assumed astype("int64") on
a parsed datetime always returns nanoseconds since epoch (dividing by
1_000_000 for ms). Modern pandas can parse into microsecond resolution
instead of nanosecond when the format string includes %f, which silently
turned the conversion into µs -> seconds instead of ns -> ms - storing
epoch SECONDS into a column meant to hold milliseconds. Confirmed via a
standalone check comparing against an independently-computed correct
value before this fix was applied. Fixed by computing epoch ms via
Timestamp/Timedelta arithmetic, which is correct regardless of pandas'
internal datetime resolution.

Handles MT5's tick-flag reality: not every row has both BID and ASK
populated. A row missing only one side (FLAGS=2 bid-only, FLAGS=4
ask-only, etc.) is a genuine partial quote update - forward-filled from
the last known value, carried across chunk boundaries. A row missing
BOTH sides is a pure Last/Volume trade tick, not a quote update - dropped,
since it carries no usable bid/ask information for this table.

Resumable by design: on every run, finds the max timestamp already
loaded for this source and skips everything up to and including it.
If interrupted, just rerun the exact same command.

Assumes the CSV is sorted ascending by time (standard for tick exports).
"""

import sqlite3
import pandas as pd
import time

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
CSV_PATH = r"C:\Users\opc\Documents\XAUUSDm_202601012305_202609180105new.csv"  # <-- update this
SYMBOL = "XAUUSD"
SOURCE = "exness_live"
CHUNK_SIZE = 500_000

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

row = cursor.execute(
    "SELECT MAX(timestamp_utc_ms) FROM ticks WHERE source = ?", (SOURCE,)
).fetchone()
resume_after_ms = row[0] if row[0] is not None else 0
print(f"Resuming after timestamp_utc_ms > {resume_after_ms:,} "
      f"({'fresh start' if resume_after_ms == 0 else 'continuing previous load'})")

start = time.time()
total_inserted = 0
total_skipped = 0
total_dropped_trade_ticks = 0
total_still_incomplete = 0

last_bid = None
last_ask = None

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")

for chunk in pd.read_csv(
    CSV_PATH,
    sep="\t",
    chunksize=CHUNK_SIZE,
):
    chunk.columns = [c.strip("<>") for c in chunk.columns]
    chunk["ts"] = pd.to_datetime(
        chunk["DATE"] + " " + chunk["TIME"], format="%Y.%m.%d %H:%M:%S.%f", utc=True
    )
    chunk["timestamp_utc_ms"] = ((chunk["ts"] - EPOCH) // pd.Timedelta(milliseconds=1)).astype("int64")
    chunk["BID"] = pd.to_numeric(chunk["BID"], errors="coerce")
    chunk["ASK"] = pd.to_numeric(chunk["ASK"], errors="coerce")

    both_missing = chunk["BID"].isna() & chunk["ASK"].isna()
    total_dropped_trade_ticks += int(both_missing.sum())
    chunk = chunk[~both_missing]

    if last_bid is not None and pd.isna(chunk["BID"].iloc[0]):
        chunk.at[chunk.index[0], "BID"] = last_bid
    if last_ask is not None and pd.isna(chunk["ASK"].iloc[0]):
        chunk.at[chunk.index[0], "ASK"] = last_ask

    chunk["BID"] = chunk["BID"].ffill()
    chunk["ASK"] = chunk["ASK"].ffill()

    if not chunk["BID"].empty:
        last_bid = chunk["BID"].iloc[-1]
        last_ask = chunk["ASK"].iloc[-1]

    still_bad = chunk["BID"].isna() | chunk["ASK"].isna()
    total_still_incomplete += int(still_bad.sum())
    chunk = chunk[~still_bad]

    new_rows = chunk[chunk["timestamp_utc_ms"] > resume_after_ms]
    total_skipped += len(chunk) - len(new_rows)

    if len(new_rows) == 0:
        continue

    rows = [
        (SYMBOL, int(r.timestamp_utc_ms), float(r.BID), float(r.ASK), SOURCE)
        for r in new_rows.itertuples(index=False)
    ]
    cursor.executemany(
        "INSERT INTO ticks (symbol, timestamp_utc_ms, bid, ask, source) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    total_inserted += len(rows)
    print(f"Inserted {total_inserted:,} rows, dropped {total_dropped_trade_ticks:,} trade-only ticks, "
          f"skipped {total_skipped:,} already-loaded, {total_still_incomplete:,} unfillable "
          f"({time.time() - start:.1f}s elapsed)")

conn.close()
print(f"\nDone. Total new rows inserted: {total_inserted:,}")
print(f"Dropped as pure trade ticks (both sides missing): {total_dropped_trade_ticks:,}")
print(f"Skipped as already-loaded duplicates: {total_skipped:,}")
print(f"Dropped as unfillable (edge case, start of file): {total_still_incomplete:,}")