"""
Phase 2 - Baseline Profiler, Piece 1: Session Range & Volatility Rhythm

Excludes the daily Exness settlement closure (20:58-22:00 UTC) from both
computations, since Dukascopy's feed is continuous through it but Exness
(where live trading happens) is not tradable during it.

Fix applied: bucket assignment now uses floor() instead of a rounding
cast - DuckDB's (x/15)::INT rounds to nearest, not truncates, which was
shifting minutes 53-59 of each 15-min window into the wrong/next bucket.
"""

import duckdb
import json
import time

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
OUT_DIR = r"C:\Users\opc\gold_ea\data"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60

SESSIONS = {
    "asian":  (0, 8),
    "london": (8, 16),
    "ny":     (13, 21),
}


def connect():
    con = duckdb.connect()
    con.execute("INSTALL sqlite;")
    con.execute("LOAD sqlite;")
    con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")
    return con


def build_minute_bars(con):
    con.execute("""
        CREATE OR REPLACE TEMP TABLE minute_bars AS
        SELECT
            date_trunc('minute', to_timestamp(timestamp_utc_ms / 1000.0)) AS minute_ts,
            (extract(hour FROM to_timestamp(timestamp_utc_ms / 1000.0)) * 60
             + extract(minute FROM to_timestamp(timestamp_utc_ms / 1000.0))) AS minute_of_day,
            min((bid + ask) / 2.0) AS low,
            max((bid + ask) / 2.0) AS high
        FROM gold.ticks
        WHERE source = 'dukascopy'
        GROUP BY 1, 2
    """)


def session_range_profile(con):
    results = {}
    for name, (start_h, end_h) in SESSIONS.items():
        start_min, end_min = start_h * 60, end_h * 60
        rows = con.execute(f"""
            WITH session_bars AS (
                SELECT date_trunc('day', minute_ts) AS day, high, low
                FROM minute_bars
                WHERE minute_of_day >= {start_min} AND minute_of_day < {end_min}
                  AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
            ),
            daily_range AS (
                SELECT day, (max(high) - min(low)) AS day_range
                FROM session_bars
                GROUP BY day
                HAVING count(*) > 30
            )
            SELECT avg(day_range), median(day_range), stddev(day_range),
                   quantile_cont(day_range, 0.1), quantile_cont(day_range, 0.9), count(*)
            FROM daily_range
        """).fetchone()
        results[name] = {
            "mean_range": round(rows[0], 3), "median_range": round(rows[1], 3),
            "std_range": round(rows[2], 3), "p10": round(rows[3], 3),
            "p90": round(rows[4], 3), "n_days": rows[5],
        }
    return results


def volatility_rhythm_profile(con):
    rows = con.execute(f"""
        WITH bucketed AS (
            SELECT floor(minute_of_day / 15.0)::INT * 15 AS bucket_start,
                   date_trunc('day', minute_ts) AS day, high, low
            FROM minute_bars
            WHERE NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        ),
        per_day_bucket AS (
            SELECT day, bucket_start, (max(high) - min(low)) AS bucket_range
            FROM bucketed GROUP BY day, bucket_start
        )
        SELECT bucket_start, avg(bucket_range), count(*)
        FROM per_day_bucket GROUP BY bucket_start ORDER BY bucket_start
    """).fetchall()

    profile = {}
    for bucket_start, mean_range, n in rows:
        h, m = divmod(int(bucket_start), 60)
        profile[f"{h:02d}:{m:02d}"] = {"mean_range": round(mean_range, 4), "n": n}
    return profile


if __name__ == "__main__":
    start = time.time()
    con = connect()

    print("Building 1-minute bars from raw ticks (scans all 282M rows - expect a few minutes)...")
    build_minute_bars(con)
    print(f"  done ({time.time() - start:.1f}s elapsed)")

    print("Computing session range profile...")
    session_profile = session_range_profile(con)
    for name, stats in session_profile.items():
        print(f"  {name:8s}  mean={stats['mean_range']}  median={stats['median_range']}  "
              f"p10={stats['p10']}  p90={stats['p90']}  n_days={stats['n_days']}")

    print("Computing intraday volatility rhythm...")
    rhythm_profile = volatility_rhythm_profile(con)
    print(f"  {len(rhythm_profile)} buckets computed")

    with open(f"{OUT_DIR}\\session_range_profile.json", "w") as f:
        json.dump(session_profile, f, indent=2)
    with open(f"{OUT_DIR}\\volatility_rhythm_profile.json", "w") as f:
        json.dump(rhythm_profile, f, indent=2)

    print(f"\nSaved session_range_profile.json and volatility_rhythm_profile.json to {OUT_DIR}")
    print(f"Total time: {time.time() - start:.1f}s")