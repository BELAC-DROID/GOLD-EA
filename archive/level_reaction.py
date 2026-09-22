"""
Phase 2, Piece 2: Round-number level-reaction profile.

Fixes applied, in order, each verified before moving to the next:
1. Away threshold loosened to $3 / 5-min lookback (from $2 / 10-min).
2. min_prior_dist bug: window-frame `level` wasn't anchored to the
   touch row -> explicit LAG(close, i) + LEAST(...).
3. LEAST(...) forced a same-minute jump into every touch -> switched
   to GREATEST(...), allowing gradual approaches.
4. Lookback silently crossed closure/weekend gaps -> added a
   lookback_span guard requiring a real unbroken 5-minute window.
5. Found via manual spot-check against real charts: approach_dir was
   computed from the TOUCH minute's own close, which can land on
   either side of the level if that minute's range already crossed
   it (common on fast approaches) - this inverted break/reject for
   those cases. Fixed by computing approach_dir from the close of
   the minute BEFORE the touch instead.
"""

import duckdb
import json

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
OUT_PATH = r"C:\Users\opc\gold_ea\data\level_reaction_profile.json"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
LEVEL_SPACING = 10
AWAY_THRESHOLD = 3.0
AWAY_LOOKBACK_MINUTES = 5
OUTCOME_THRESHOLD = 2.0
LOOKAHEAD_MINUTES = 15

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

def summarize(where_clause="1=1"):
    rows = con.execute(f"""
        SELECT outcome, count(*) FROM classified
        WHERE outcome != 'no_data' AND {where_clause}
        GROUP BY outcome
    """).fetchall()
    total = sum(c for _, c in rows)
    return {outcome: {"count": c, "pct": round(100 * c / total, 1)} for outcome, c in rows} if total else {}

profile = {
    "params": {
        "level_spacing": LEVEL_SPACING, "away_threshold": AWAY_THRESHOLD,
        "away_lookback_minutes": AWAY_LOOKBACK_MINUTES,
        "outcome_threshold": OUTCOME_THRESHOLD, "lookahead_minutes": LOOKAHEAD_MINUTES,
    },
    "all_levels": summarize(),
    "major_levels_50": summarize("is_major_level = true"),
    "minor_levels_10": summarize("is_major_level = false"),
}

total_touches = con.execute("SELECT count(*) FROM classified WHERE outcome != 'no_data'").fetchone()[0]
print(f"Total classifiable touch events: {total_touches:,}")
print(json.dumps(profile, indent=2))

with open(OUT_PATH, "w") as f:
    json.dump(profile, f, indent=2)
print(f"\nSaved to {OUT_PATH}")