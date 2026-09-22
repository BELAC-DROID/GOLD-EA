import sqlite3

conn = sqlite3.connect(r"C:\Users\opc\gold_ea\data\gold_data.db")
cur = conn.cursor()

keywords = ["Non-Farm", "Nonfarm", "NFP", "CPI", "FOMC", "PCE", "GDP", "Powell"]

for kw in keywords:
    cur.execute("""
        SELECT DISTINCT event_name, importance, COUNT(*) c
        FROM calendar_events
        WHERE currency = 'USD' AND event_name LIKE ?
        GROUP BY event_name, importance
        ORDER BY c DESC
    """, (f"%{kw}%",))
    rows = cur.fetchall()
    if rows:
        print(f"--- matches for '{kw}' ---")
        for name, imp, c in rows:
            print(f"  importance={imp}  n={c:4d}  {name}")

conn.close()