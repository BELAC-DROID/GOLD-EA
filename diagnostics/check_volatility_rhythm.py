"""
Diagnostic: verify volatility_rhythm_profile() in baseline_profiler.py
after the floor() bucketing fix (never independently spot-checked since
that fix was applied).

Checks:
1. Rebuilds minute_bars from raw ticks and recomputes the rhythm profile.
2. Confirms the "21:00" bucket (1260-1274, fully inside the 20:58-22:00
   closure) is absent or has ~0 data - the original symptom this whole
   fix was chasing.
3. Confirms the "20:45" bucket (1245-1259, which straddles the closure
   START at 1258) reflects only the 13 clean minutes (1245-1257), not
   the full 15 - worth knowing this bucket is a partial window by design.
4. Independently recomputes mean_range for two arbitrary, closure-free
   buckets directly from minute_bars (not reusing the grouped query),
   and compares against the profile's own numbers.
"""

import duckdb
import json

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60

con = duckdb.connect()
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")

print("Building 1-minute bars (scans all ticks - may take a few minutes)...")
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
print("  done.\n")

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

print(f"{len(profile)} buckets computed.\n")

print("--- Check 1: '21:00' bucket - should be ABSENT or have ~0 n (fully inside closure) ---")
print(profile.get("21:00", "Not present in profile - fully excluded, as expected."))

print("\n--- Check 2: '20:45' bucket - straddles closure start (1258), so this is a ---")
print("--- PARTIAL 13-minute window (1245-1257), not a full 15-minute bucket -------")
print(profile.get("20:45"))

print("\n--- Check 3: independent recompute of two arbitrary closure-free buckets ---")
for check_bucket in [180, 600]:  # 03:00 and 10:00, both far from the closure
    h, m = divmod(check_bucket, 60)
    label = f"{h:02d}:{m:02d}"
    manual = con.execute(f"""
        WITH day_bucket AS (
            SELECT date_trunc('day', minute_ts) AS day,
                   max(high) - min(low) AS bucket_range
            FROM minute_bars
            WHERE minute_of_day >= {check_bucket} AND minute_of_day < {check_bucket + 15}
            GROUP BY day
        )
        SELECT avg(bucket_range), count(*) FROM day_bucket
    """).fetchone()
    print(f"\n  Bucket {label}:")
    print(f"    From grouped profile:      {profile.get(label)}")
    print(f"    Independently recomputed:  mean_range={round(manual[0], 4)}, n={manual[1]}")

with open(r"C:\Users\opc\gold_ea\data\volatility_rhythm_profile_check.json", "w") as f:
    json.dump(profile, f, indent=2)
print("\nSaved full profile to volatility_rhythm_profile_check.json for reference.")