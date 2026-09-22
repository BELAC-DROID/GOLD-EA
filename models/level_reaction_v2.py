"""
Phase 2: price-tiered round-number level-reaction classifier.
Logic lives in level_reaction_core.py; this script aggregates and
reports it. See level_reaction_core.py for tiering rationale.
"""

import duckdb
import json
from level_reaction_core import TIERS, build_classified_for_tier

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
OUT_PATH = r"C:\Users\opc\gold_ea\data\level_reaction_profile_tiered.json"

con = duckdb.connect(ANALYTICS_DB)


def summarize_tier(tier):
    build_classified_for_tier(con, tier, "p")

    def summarize(where_clause="1=1"):
        rows = con.execute(f"""
            SELECT outcome, count(*) FROM p_classified
            WHERE outcome != 'no_data' AND {where_clause}
            GROUP BY outcome
        """).fetchall()
        total = sum(c for _, c in rows)
        return {o: {"count": c, "pct": round(100 * c / total, 1)} for o, c in rows} if total else {}

    total_touches = con.execute("SELECT count(*) FROM p_classified WHERE outcome != 'no_data'").fetchone()[0]

    price_filter_parts = []
    if tier["price_min"] is not None:
        price_filter_parts.append(f"close >= {tier['price_min']}")
    if tier["price_max"] is not None:
        price_filter_parts.append(f"close < {tier['price_max']}")
    price_filter = " AND ".join(price_filter_parts) if price_filter_parts else "1=1"
    n_days = con.execute(f"""
        SELECT count(DISTINCT date_trunc('day', minute_ts)) FROM minute_bars_ohlc WHERE {price_filter}
    """).fetchone()[0]

    return {
        "params": {**{k: tier[k] for k in ("level_spacing", "major_multiple", "away_threshold",
                                            "outcome_threshold", "price_min", "price_max")},
                   "away_lookback_minutes": 5, "lookahead_minutes": 15},
        "n_trading_days_in_tier": n_days,
        "total_touches": total_touches,
        "touches_per_day": round(total_touches / n_days, 2) if n_days else None,
        "all_levels": summarize(),
        "major_levels": summarize("is_major_level = true"),
        "minor_levels": summarize("is_major_level = false"),
    }


results = {}
for tier in TIERS:
    print(f"=== {tier['name']} (spacing=${tier['level_spacing']}/{tier['major_multiple']}, "
          f"price {tier['price_min']}-{tier['price_max']}) ===")
    result = summarize_tier(tier)
    results[tier["name"]] = result
    print(f"  {result['n_trading_days_in_tier']} trading days in tier, "
          f"{result['total_touches']:,} touches, {result['touches_per_day']} touches/day")
    print(f"  all_levels: {json.dumps(result['all_levels'])}")
    print()

with open(OUT_PATH, "w") as f:
    json.dump(results, f, indent=2)
print(f"Saved to {OUT_PATH}")