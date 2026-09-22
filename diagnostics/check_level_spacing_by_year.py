"""
Test whether fixed $10/$50 round-number level spacing has degraded as
gold's price rose from ~$1,300 (2019) toward ~$3,400+ (2025) - i.e.
whether the level_reaction.py touch-detection mechanism itself has
lost relevance as price moved further from the range it was tuned on.

This does NOT reclassify outcomes (reject/break/consolidate) - it just
checks touch FREQUENCY per year, since a level-spacing problem would
show up first as levels becoming too fine (too many touches, packed
too closely together relative to typical price movement) or too coarse
(touches becoming rare) as price scales.
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
    SELECT *
    FROM flagged
    WHERE touching = true
      AND (prev_touching = false OR prev_touching IS NULL)
      AND max_prior_dist > {AWAY_THRESHOLD}
      AND lookback_span = INTERVAL '{AWAY_LOOKBACK_MINUTES} minutes'
""")

print("Touch frequency and average price level, by year:\n")
print(con.execute("""
    SELECT
        extract(year FROM minute_ts) AS year,
        count(*) AS n_touches,
        round(avg(level), 1) AS avg_level_touched,
        round(min(level), 1) AS min_level,
        round(max(level), 1) AS max_level
    FROM first_touches
    GROUP BY year
    ORDER BY year
""").fetchdf().to_string(index=False))

print("\nFor comparison, trading days per year (denominator context):")
print(con.execute("""
    SELECT extract(year FROM minute_ts) AS year, count(DISTINCT date_trunc('day', minute_ts)) AS n_days
    FROM minute_bars_ohlc
    GROUP BY year
    ORDER BY year
""").fetchdf().to_string(index=False))