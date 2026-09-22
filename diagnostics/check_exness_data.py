import sqlite3
import csv
import datetime

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
CSV_PATH = r"C:\Users\opc\gold_ea\data\calendar_history_full.csv"  # adjust path if it's elsewhere

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS calendar_events (
        event_id TEXT,
        event_name TEXT,
        country_code TEXT,
        currency TEXT,
        importance INTEGER,
        time_utc TEXT,
        timestamp_utc_ms INTEGER,
        actual REAL,
        forecast REAL,
        previous REAL,
        revised_previous REAL
    )
""")

cur.execute("DELETE FROM calendar_events")
conn.commit()

def to_float(s):
    return float(s) if s.strip() != "" else None

def to_epoch_ms(time_str):
    dt = datetime.datetime.strptime(time_str, "%Y.%m.%d %H:%M:%S")
    dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)

EXPECTED_COLS = 10  # event_id, event_name, country_code, currency, importance,
                     # time_utc, actual, forecast, previous, revised_previous

rows_inserted = 0
rows_fixed = 0
with open(CSV_PATH, newline="", encoding="cp1252") as f:
    reader = csv.reader(f)
    header = next(reader)  # skip header row

    batch = []
    for line_num, row in enumerate(reader, start=2):
        n = len(row)
        extra = n - EXPECTED_COLS

        if extra > 0:
            # event_name got split by an unescaped comma in MQL5's CSV writer -
            # merge the surplus fields back into event_name (the only free-text
            # column; every other field is a fixed code/number, so this is safe)
            event_id = row[0]
            event_name = ",".join(row[1:2 + extra])
            country_code = row[2 + extra]
            currency = row[3 + extra]
            importance = row[4 + extra]
            time_utc = row[5 + extra]
            actual = row[6 + extra]
            forecast = row[7 + extra]
            previous = row[8 + extra]
            revised_previous = row[9 + extra]
            rows_fixed += 1
        elif extra < 0:
            print(f"Line {line_num}: fewer columns than expected ({n}), skipping: {row}")
            continue
        else:
            event_id, event_name, country_code, currency, importance, \
                time_utc, actual, forecast, previous, revised_previous = row

        try:
            ts_ms = to_epoch_ms(time_utc)
        except ValueError:
            print(f"Line {line_num}: could not parse time_utc={time_utc!r}, skipping: {row}")
            continue

        batch.append((
            event_id,
            event_name,
            country_code,
            currency,
            int(importance) if importance != "" else None,
            time_utc,
            ts_ms,
            to_float(actual),
            to_float(forecast),
            to_float(previous),
            to_float(revised_previous),
        ))

        if len(batch) >= 5000:
            cur.executemany(
                "INSERT INTO calendar_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch
            )
            rows_inserted += len(batch)
            batch = []

    if batch:
        cur.executemany(
            "INSERT INTO calendar_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch
        )
        rows_inserted += len(batch)

conn.commit()

cur.execute("CREATE INDEX IF NOT EXISTS idx_calendar_ts ON calendar_events(timestamp_utc_ms)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_calendar_importance ON calendar_events(importance, currency)")
conn.commit()

print(f"Done. Total events inserted: {rows_inserted:,}  (comma-split rows auto-repaired: {rows_fixed:,})")

conn.close()