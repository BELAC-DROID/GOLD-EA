"""
Diagnostic: check whether any first-touch events have their 5-minute
lookback silently crossing the daily 20:58-22:00 closure gap, which
would make max_prior_dist meaningless for those rows (comparing against
stale pre-closure price instead of real recent price action).
"""

import duckdb

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
LEVEL_SPACING = 10
AWAY_THRESHOLD = 3.0
AWAY_LOOKBACK_MINUTES = 5

con = duckdb.connect(ANALYTICS_DB)

con.execute(f"""
    CREATE OR REPLACE TEMP TABLE bars AS
    SELECT minute_ts, minute_of_day, close, high, low,
           round(close / {LEVEL_SPACING}.0) * {LEVEL_SPACING} AS level
    FROM minute_bars_ohlc
    WHERE NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
""")

lag_terms = ",\n           ".join(
    f"ABS(LAG(close, {i}) OVER (ORDER BY minute_ts) - level)"
    for i in range(1, AWAY_LOOKBACK_MINUTES + 1)
)

con.execute(f"""
    CREATE OR REPLACE TEMP TABLE flagged AS
    SELECT *,
           (low <= level AND high >= level) AS touching,
           LAG(low <= level AND high >= level) OVER (ORDER BY minute_ts) AS prev_touching,
           GREATEST({lag_terms}) AS max_prior_dist,
           minute_ts - LAG(minute_ts, {AWAY_LOOKBACK_MINUTES}) OVER (ORDER BY minute_ts) AS lookback_span
    FROM bars
""")

con.execute(f"""
    CREATE OR REPLACE TEMP TABLE first_touches AS
    SELECT *, sign(level - close) AS approach_dir
    FROM flagged
    WHERE touching = true
      AND (prev_touching = false OR prev_touching IS NULL)
      AND max_prior_dist > {AWAY_THRESHOLD}
""")

total = con.execute("SELECT count(*) FROM first_touches").fetchone()[0]
print(f"Total first-touch events: {total:,}")

# lookback_span should be exactly 5 minutes if the window is clean.
# Anything longer means the lookback silently crossed the closure gap.
bad = con.execute(f"""
    SELECT count(*) FROM first_touches
    WHERE lookback_span > INTERVAL '{AWAY_LOOKBACK_MINUTES} minutes'
""").fetchone()[0]
print(f"Touches whose lookback crosses the closure gap (span > {AWAY_LOOKBACK_MINUTES} min): {bad:,}")

print("\nSample of the gap-crossing rows (if any):")
sample = con.execute(f"""
    SELECT minute_ts, close, level, max_prior_dist, lookback_span
    FROM first_touches
    WHERE lookback_span > INTERVAL '{AWAY_LOOKBACK_MINUTES} minutes'
    ORDER BY minute_ts
    LIMIT 10
""").fetchdf()
print(sample)