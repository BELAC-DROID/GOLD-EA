"""
Bin touch frequency directly by the PRICE LEVEL being touched (not
calendar year), to find where fixed $10 spacing actually starts
breaking down - this gives real candidate boundaries for a price-tiered
spacing scheme, rather than guessing at round numbers.

Denominator: for each price bucket, count how many TRADING DAYS had
their day's average price fall in that bucket, so touches/day is a
fair rate, not just a raw count inflated by more days at higher prices.
"""

import duckdb

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
LEVEL_SPACING = 10
AWAY_THRESHOLD = 3.0
AWAY_LOOKBACK_MINUTES = 5
PRICE_BUCKET_SIZE = 250  # bin width for this diagnostic only

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
    SELECT *,
           floor(level / {PRICE_BUCKET_SIZE}.0) * {PRICE_BUCKET_SIZE} AS price_bucket
    FROM flagged
    WHERE touching = true
      AND (prev_touching = false OR prev_touching IS NULL)
      AND max_prior_dist > {AWAY_THRESHOLD}
      AND lookback_span = INTERVAL '{AWAY_LOOKBACK_MINUTES} minutes'
""")

# Denominator: trading days whose average daily close falls in each price bucket
con.execute(f"""
    CREATE OR REPLACE TEMP TABLE daily_avg_price AS
    SELECT date_trunc('day', minute_ts) AS day,
           avg(close) AS avg_price,
           floor(avg(close) / {PRICE_BUCKET_SIZE}.0) * {PRICE_BUCKET_SIZE} AS price_bucket
    FROM minute_bars_ohlc
    GROUP BY day
""")

touch_counts = con.execute("""
    SELECT price_bucket, count(*) AS n_touches
    FROM first_touches
    GROUP BY price_bucket
""").fetchdf()

day_counts = con.execute("""
    SELECT price_bucket, count(*) AS n_days
    FROM daily_avg_price
    GROUP BY price_bucket
""").fetchdf()

merged = day_counts.merge(touch_counts, on="price_bucket", how="left").fillna(0)
merged["n_touches"] = merged["n_touches"].astype(int)
merged["touches_per_day"] = (merged["n_touches"] / merged["n_days"]).round(2)
merged = merged.sort_values("price_bucket")

print(f"Touch frequency by ${PRICE_BUCKET_SIZE} price bucket:\n")
print(merged.to_string(index=False))