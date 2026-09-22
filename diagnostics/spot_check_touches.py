"""
Spot-check: pull a handful of real classified touch events and show the
actual price path around each one, so we can eyeball whether the
reject/break/consolidate label matches what a human would call it.

Kept in sync with level_reaction.py's approach_dir fix: direction is
computed from the close BEFORE the touch minute, not the touch minute's
own close (which can land on either side of the level after crossing it).
"""

import duckdb

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
LEVEL_SPACING = 10
AWAY_THRESHOLD = 3.0
AWAY_LOOKBACK_MINUTES = 5
OUTCOME_THRESHOLD = 2.0
LOOKAHEAD_MINUTES = 15
CONTEXT_MINUTES = 20

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
           LAG(close, 1) OVER (ORDER BY minute_ts) AS prior_close,
           GREATEST({lag_terms}) AS max_prior_dist,
           minute_ts - LAG(minute_ts, {AWAY_LOOKBACK_MINUTES}) OVER (ORDER BY minute_ts) AS lookback_span
    FROM bars
""")

con.execute(f"""
    CREATE OR REPLACE TEMP TABLE first_touches AS
    SELECT *, sign(level - prior_close) AS approach_dir
    FROM flagged
    WHERE touching = true
      AND (prev_touching = false OR prev_touching IS NULL)
      AND max_prior_dist > {AWAY_THRESHOLD}
      AND lookback_span = INTERVAL '{AWAY_LOOKBACK_MINUTES} minutes'
""")

con.execute(f"""
    CREATE OR REPLACE TEMP TABLE reaction_results AS
    SELECT t.minute_ts, t.level AS touched_level, t.approach_dir,
           (t.level % 50 = 0) AS is_major_level,
           f.close AS future_close
    FROM first_touches t
    LEFT JOIN minute_bars_ohlc f
      ON f.minute_ts = t.minute_ts + INTERVAL '{LOOKAHEAD_MINUTES} minutes'
""")

con.execute(f"""
    CREATE OR REPLACE TEMP TABLE classified AS
    SELECT *,
        CASE
            WHEN future_close IS NULL THEN 'no_data'
            WHEN sign(future_close - touched_level) = approach_dir
                 AND abs(future_close - touched_level) >= {OUTCOME_THRESHOLD} THEN 'break'
            WHEN sign(future_close - touched_level) != approach_dir
                 AND abs(future_close - touched_level) >= {OUTCOME_THRESHOLD} THEN 'reject'
            ELSE 'consolidate'
        END AS outcome
    FROM reaction_results
""")

picks = con.execute("""
    SELECT minute_ts, touched_level, approach_dir, outcome, future_close, is_major_level
    FROM classified
    WHERE outcome != 'no_data'
    QUALIFY row_number() OVER (PARTITION BY outcome ORDER BY minute_ts) = 1
       OR row_number() OVER (PARTITION BY outcome ORDER BY minute_ts DESC) = 1
    ORDER BY outcome, minute_ts
""").fetchdf()

print("Picked examples (one early, one late, per outcome):\n")
print(picks)
print("\n" + "=" * 80 + "\n")

for _, row in picks.iterrows():
    ts = row["minute_ts"]
    level = row["touched_level"]
    outcome = row["outcome"]
    direction = "up toward" if row["approach_dir"] > 0 else "down toward"

    print(f"--- Touch at {ts} | level={level} | approached from {direction} it "
          f"| classified as: {outcome.upper()} | major_level={row['is_major_level']} ---")

    context = con.execute(f"""
        SELECT minute_ts, close, high, low
        FROM minute_bars_ohlc
        WHERE minute_ts BETWEEN TIMESTAMP '{ts}' - INTERVAL '{CONTEXT_MINUTES} minutes'
                             AND TIMESTAMP '{ts}' + INTERVAL '{CONTEXT_MINUTES} minutes'
        ORDER BY minute_ts
    """).fetchdf()

    print(context.to_string(index=False))
    print("\n" + "=" * 80 + "\n")