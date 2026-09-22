"""
Shared tiering/classification logic for level-reaction analysis.
Both level_reaction_v2.py (the trusted profile) and
test1_level_reaction_walkforward.py (Phase 3 calibration) import from
here, so tier definitions and thresholds can't drift apart between the
two the way the original walk-forward script did.
"""

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60
AWAY_LOOKBACK_MINUTES = 5
LOOKAHEAD_MINUTES = 15

TIERS = [
    {
        "name": "tier1_under_3000",
        "price_min": None, "price_max": 3000,
        "level_spacing": 10, "major_multiple": 50,
        "away_threshold": 3.0, "outcome_threshold": 2.0,
    },
    {
        "name": "tier2_3000_and_above",
        "price_min": 3000, "price_max": None,
        "level_spacing": 25, "major_multiple": 100,
        "away_threshold": 7.5, "outcome_threshold": 5.0,
    },
]


def build_classified_for_tier(con, tier, temp_prefix):
    """Creates {temp_prefix}_classified with one row per touch:
    (day, tier_name, is_major_level, outcome). Row-level, not
    pre-aggregated - so both the trusted profile (which aggregates)
    and the walk-forward harness (which needs per-day/per-split
    slicing) can use the same underlying classification."""
    price_filter_parts = []
    if tier["price_min"] is not None:
        price_filter_parts.append(f"close >= {tier['price_min']}")
    if tier["price_max"] is not None:
        price_filter_parts.append(f"close < {tier['price_max']}")
    price_filter = " AND ".join(price_filter_parts) if price_filter_parts else "1=1"

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {temp_prefix}_bars AS
        SELECT minute_ts, minute_of_day, close, high, low,
               round(close / {tier['level_spacing']}.0) * {tier['level_spacing']} AS level
        FROM minute_bars_ohlc
        WHERE NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
          AND {price_filter}
    """)

    lag_terms = ",\n           ".join(
        f"ABS(LAG(close, {i}) OVER (ORDER BY minute_ts) - level)"
        for i in range(1, AWAY_LOOKBACK_MINUTES + 1)
    )

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {temp_prefix}_flagged AS
        SELECT *,
               (low <= level AND high >= level) AS touching,
               LAG(low <= level AND high >= level) OVER (ORDER BY minute_ts) AS prev_touching,
               LAG(close, 1) OVER (ORDER BY minute_ts) AS prior_close,
               GREATEST({lag_terms}) AS max_prior_dist,
               minute_ts - LAG(minute_ts, {AWAY_LOOKBACK_MINUTES}) OVER (ORDER BY minute_ts) AS lookback_span
        FROM {temp_prefix}_bars
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {temp_prefix}_first_touches AS
        SELECT *, sign(level - prior_close) AS approach_dir
        FROM {temp_prefix}_flagged
        WHERE touching = true
          AND (prev_touching = false OR prev_touching IS NULL)
          AND max_prior_dist > {tier['away_threshold']}
          AND lookback_span = INTERVAL '{AWAY_LOOKBACK_MINUTES} minutes'
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {temp_prefix}_reaction_results AS
        SELECT t.minute_ts, date_trunc('day', t.minute_ts) AS day,
               t.level AS touched_level, t.approach_dir,
               (t.level % {tier['major_multiple']} = 0) AS is_major_level,
               f.close AS future_close
        FROM {temp_prefix}_first_touches t
        LEFT JOIN minute_bars_ohlc f
          ON f.minute_ts = t.minute_ts + INTERVAL '{LOOKAHEAD_MINUTES} minutes'
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {temp_prefix}_classified AS
        SELECT day, '{tier["name"]}' AS tier_name, is_major_level,
            CASE
                WHEN future_close IS NULL THEN 'no_data'
                WHEN sign(future_close - touched_level) = approach_dir
                     AND abs(future_close - touched_level) >= {tier['outcome_threshold']} THEN 'break'
                WHEN sign(future_close - touched_level) != approach_dir
                     AND abs(future_close - touched_level) >= {tier['outcome_threshold']} THEN 'reject'
                ELSE 'consolidate'
            END AS outcome
        FROM {temp_prefix}_reaction_results
        WHERE future_close IS NOT NULL
    """)


def build_classified_all_tiers(con):
    """Builds one combined `classified_all` table across every tier in
    TIERS: (day, tier_name, is_major_level, outcome)."""
    tier_tables = []
    for i, tier in enumerate(TIERS):
        prefix = f"t{i}"
        build_classified_for_tier(con, tier, prefix)
        tier_tables.append(f"{prefix}_classified")

    union_sql = "\nUNION ALL\n".join(f"SELECT * FROM {t}" for t in tier_tables)
    con.execute(f"CREATE OR REPLACE TEMP TABLE classified_all AS {union_sql}")