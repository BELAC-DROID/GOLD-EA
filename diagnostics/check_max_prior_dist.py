"""
Diagnostic: verify the GREATEST-based away-check fix for level_reaction.py.

Rebuilds bars -> flagged -> first_touches with max_prior_dist (GREATEST
instead of LEAST), then prints a sample of first-touch rows alongside the
single-minute jump into each touch, so we can confirm gradual approaches
are now being captured instead of only sudden jumps.
"""

import duckdb

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
LEVEL_SPACING = 10
AWAY_THRESHOLD = 3.0
AWAY_LOOKBACK_MINUTES = 5

con = duckdb.connect(ANALYTICS_DB)

# Step 1: minute bars with round-number level assigned
con.execute(f"""
    CREATE OR REPLACE TEMP TABLE bars AS
    SELECT minute_ts, minute_of_day, close, high, low,
           round(close / {LEVEL_SPACING}.0) * {LEVEL_SPACING} AS level
    FROM minute_bars_ohlc
    WHERE NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
""")

# Step 2: flag touches, and compute max_prior_dist (GREATEST fix)
lag_terms = ",\n           ".join(
    f"ABS(LAG(close, {i}) OVER (ORDER BY minute_ts) - level)"
    for i in range(1, AWAY_LOOKBACK_MINUTES + 1)
)

con.execute(f"""
    CREATE OR REPLACE TEMP TABLE flagged AS
    SELECT *,
           (low <= level AND high >= level) AS touching,
           LAG(low <= level AND high >= level) OVER (ORDER BY minute_ts) AS prev_touching,
           GREATEST({lag_terms}) AS max_prior_dist
    FROM bars
""")

# Step 3: first touches (genuine approach-and-touch events)
con.execute(f"""
    CREATE OR REPLACE TEMP TABLE first_touches AS
    SELECT *, sign(level - close) AS approach_dir
    FROM flagged
    WHERE touching = true
      AND (prev_touching = false OR prev_touching IS NULL)
      AND max_prior_dist > {AWAY_THRESHOLD}
""")

total = con.execute("SELECT count(*) FROM first_touches").fetchone()[0]
print(f"Total first-touch events found: {total:,}\n")

# Step 4: diagnostic - check the single-minute jump into each touch
print("Sample of first 20 touches, with the jump from the minute before:\n")
result = con.execute("""
    SELECT ft.minute_ts, ft.close, ft.level, ft.max_prior_dist,
           prev.close AS prev_minute_close,
           ft.close - prev.close AS one_min_jump
    FROM first_touches ft
    LEFT JOIN bars prev
      ON prev.minute_ts = ft.minute_ts - INTERVAL '1 minute'
    ORDER BY ft.minute_ts
    LIMIT 20
""").fetchdf()

print(result)