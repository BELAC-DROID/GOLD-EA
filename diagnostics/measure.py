import duckdb

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
con = duckdb.connect(ANALYTICS_DB)

con.execute("""
    CREATE OR REPLACE TEMP TABLE bars AS
    SELECT minute_ts, close, high, low,
           round(close / 10.0) * 10 AS level
    FROM minute_bars_ohlc
""")

con.execute("""
    CREATE OR REPLACE TEMP TABLE flagged AS
    SELECT *,
           (low <= level AND high >= level) AS touching,
           LAG(low <= level AND high >= level) OVER (ORDER BY minute_ts) AS prev_touching
    FROM bars
""")

con.execute("""
    CREATE OR REPLACE TEMP TABLE first_touches AS
    SELECT * FROM flagged
    WHERE touching = true AND (prev_touching = false OR prev_touching IS NULL)
""")

n_first_touches = con.execute("SELECT count(*) FROM first_touches").fetchone()[0]
print(f"Stage 1 - raw first-touch episodes (before any away filter): {n_first_touches:,}")

# How many of those first-touches have an exact bar at exactly -10min?
n_with_exact_ref = con.execute("""
    SELECT count(*) FROM first_touches ft
    JOIN minute_bars_ohlc ref ON ref.minute_ts = ft.minute_ts - INTERVAL '10 minutes'
""").fetchone()[0]
print(f"Stage 2 - first-touches with an exact bar at -10min: {n_with_exact_ref:,}")
print(f"  -> dropped purely by missing exact-minute data: {n_first_touches - n_with_exact_ref:,}")

# Of those with a valid ref bar, how many pass the away-window check?
n_passing_away = con.execute("""
    SELECT count(*) FROM first_touches ft
    JOIN minute_bars_ohlc ref ON ref.minute_ts = ft.minute_ts - INTERVAL '10 minutes'
    WHERE (
        SELECT MIN(ABS(b.close - ft.level))
        FROM minute_bars_ohlc b
        WHERE b.minute_ts BETWEEN ft.minute_ts - INTERVAL '10 minutes' AND ft.minute_ts - INTERVAL '1 minute'
    ) > 2.0
""").fetchone()[0]
print(f"Stage 3 - passing the >$2 away-window check: {n_passing_away:,}")