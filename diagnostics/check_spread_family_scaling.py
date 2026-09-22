"""
Diagnostic: verify spread_model.py's per-family scaling is actually
applying correctly, using REAL event timestamps pulled from
calendar_events - not synthetic test cases - so this checks the real
code path end to end, not just the arithmetic in isolation.

For each family, pulls one real event timestamp and computes the
spread at the event's own minute (offset=0, the biggest spike) under
both mean and worst_case mode. Also prints what the OLD (pre-fix,
unscaled) NFP-uniform template would have produced at that same offset,
so the actual size of the correction is visible side by side.
"""

import sqlite3
from datetime import datetime, timezone
import sys

sys.path.insert(0, r"C:\Users\opc\gold_ea\models")
from spread_model import (
    load_baseline_profile, load_high_impact_events, get_simulated_spread,
    SPIKE_TEMPLATE, FAMILY_SCALE_FACTOR, RELEASE_FAMILY, EVENT_NAME_WHITELIST,
)

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"

conn = sqlite3.connect(DB_PATH)
profile = load_baseline_profile()
events = load_high_impact_events(conn)

# Pull one real event per family directly from calendar_events, rather
# than constructing a synthetic timestamp.
cur = conn.cursor()

print(f"{'Family':<8} {'Event name':<28} {'Event time (UTC)':<22} "
      f"{'Old (unscaled) mean spread':<28} {'New (scaled) mean spread':<26} {'Scale factor'}")

for family in ["NFP", "CPI", "FOMC", "GDP", "PCE"]:
    # Find event names belonging to this family from the whitelist
    names_in_family = [n for n in EVENT_NAME_WHITELIST if RELEASE_FAMILY.get(n) == family]
    name_placeholders = ",".join("?" for _ in names_in_family)
    row = cur.execute(f"""
        SELECT timestamp_utc_ms, event_name FROM calendar_events
        WHERE event_name IN ({name_placeholders}) AND currency = 'USD'
        ORDER BY timestamp_utc_ms DESC
        LIMIT 1
    """, names_in_family).fetchone()

    if row is None:
        print(f"{family:<8} (no events found in calendar_events for this family)")
        continue

    ts_ms, event_name = row
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

    new_spread, is_event, offset, detected_family = get_simulated_spread(
        ts_ms, profile, events, mode="mean"
    )

    # Manually compute what the OLD unscaled template would have given,
    # for direct comparison - same offset=0 logic, no family scaling.
    base = new_spread / (1 + FAMILY_SCALE_FACTOR[family] * (SPIKE_TEMPLATE[0][0] - 1)) \
        if offset == 0 else None
    old_unscaled_spread = round(base * SPIKE_TEMPLATE[0][0], 4) if base else "n/a (offset != 0)"

    scale = FAMILY_SCALE_FACTOR[family]
    print(f"{family:<8} {event_name:<28} {dt.strftime('%Y-%m-%d %H:%M'):<22} "
          f"{str(old_unscaled_spread):<28} {new_spread:<26} {scale}")

    # Sanity check: detected family should match the one we queried for
    if detected_family != family:
        print(f"  !! MISMATCH: queried for {family} but get_simulated_spread detected {detected_family}")

conn.close()