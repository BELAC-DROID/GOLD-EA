import sqlite3

conn = sqlite3.connect(r"C:\Users\opc\gold_ea\data\gold_data.db")
cur = conn.cursor()

cur.execute("""
    SELECT event_name, COUNT(*) c
    FROM calendar_events
    WHERE importance >= 3 AND currency = 'USD'
    GROUP BY event_name
    ORDER BY c DESC
    LIMIT 20
""")
print("Top 20 most frequent 'importance=3, USD' event names:")
for name, c in cur.fetchall():
    print(f"  {c:5d}  {name}")

conn.close()