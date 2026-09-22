"""
Exness-realistic spread simulation model for XAU/USD backtesting.

Combines:
  1. A flat time-of-day baseline (from normal_day_spread_profile.json).
  2. An event-driven spike/decay overlay, scaled per release family.

UPDATE (closes the original limitation flagged below): Metric J
(catalyst magnitude prediction, Phase 3) tested whether NFP's spike
shape generalizes to the other 4 release families and found it does
NOT (p<0.0001) - NFP moves gold ~0.365% of price on average, vs CPI
0.328%, FOMC 0.253%, GDP 0.150%, PCE 0.124%. SPIKE_TEMPLATE below is
now scaled per family using these measured ratios.

ASSUMPTION being made explicit, not proven: this uses price-magnitude
ratios as a proxy for spread-widening ratios. Metric J measured price
moves, not spread behavior directly - no one has directly measured
Exness spread behavior around a GDP or PCE release the way the
original NFP spike was measured from real tick data. Reasonable
(bigger moves plausibly cause more liquidity dry-up/slippage) but
still an assumption, flagged so it isn't mistaken for a second
confirmed fact.

ORIGINAL LIMITATION (now addressed above, kept for history): the base
spike shape (offsets -1 to +8, "shock then decay") is derived from
exactly ONE observed event - the Sept 4, 2026 NFP release - and was
originally applied uniformly to every event type. The per-family
scaling above corrects for amplitude; the underlying shock-then-decay
SHAPE itself is still only validated against that one NFP event.
"""

import sqlite3
import json
import bisect
from datetime import datetime, timezone

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
BASELINE_PROFILE_PATH = r"C:\Users\opc\gold_ea\data\normal_day_spread_profile.json"

# Minute offset relative to event time -> (mean_multiplier, max_multiplier).
# This is the NFP-calibrated reference shape - per-family scaling is
# applied on top of this at lookup time, not baked in here.
SPIKE_TEMPLATE = {
    -1: (1.15, 1.85),
     0: (1.96, 7.69),
     1: (1.24, 2.23),
     2: (1.30, 2.23),
     3: (1.40, 2.23),
     4: (1.15, 2.23),
     5: (1.04, 1.31),
     6: (1.01, 1.31),
     7: (1.01, 1.31),
     8: (1.02, 1.31),
}
MIN_OFFSET = min(SPIKE_TEMPLATE)
MAX_OFFSET = max(SPIKE_TEMPLATE)

EVENT_CURRENCIES = ("USD",)

EVENT_NAME_WHITELIST = (
    "Nonfarm Payrolls",
    "CPI",
    "CPI y/y",
    "CPI m/m",
    "Core CPI m/m",
    "Core CPI n.s.a. m/m",
    "Core PCE Price Index m/m",
    "Core PCE Price Index y/y",
    "FOMC Statement",
    "FOMC Press Conference",
    "GDP q/q",
)

# Maps each whitelisted event name to its release family - same mapping
# used in Metric J's catalyst_magnitude_prediction.py, so the two stay
# consistent with each other.
RELEASE_FAMILY = {
    "Nonfarm Payrolls": "NFP",
    "CPI": "CPI", "CPI y/y": "CPI", "CPI m/m": "CPI",
    "Core CPI m/m": "CPI", "Core CPI n.s.a. m/m": "CPI",
    "Core PCE Price Index m/m": "PCE", "Core PCE Price Index y/y": "PCE",
    "FOMC Statement": "FOMC", "FOMC Press Conference": "FOMC",
    "GDP q/q": "GDP",
}

# Per-family scale factor applied to the (multiplier - 1) excess over
# baseline, derived from Metric J's measured mean price-magnitude per
# family, each relative to NFP (the template's own calibration source,
# hence 1.00). See module docstring for the assumption this rests on.
#   NFP: 0.365% of price (reference, ratio = 1.00)
#   CPI: 0.328% -> 0.328/0.365 = 0.90
#   FOMC: 0.253% -> 0.253/0.365 = 0.69
#   GDP: 0.150% -> 0.150/0.365 = 0.41
#   PCE: 0.124% -> 0.124/0.365 = 0.34
FAMILY_SCALE_FACTOR = {
    "NFP": 1.00,
    "CPI": 0.90,
    "FOMC": 0.69,
    "GDP": 0.41,
    "PCE": 0.34,
}


def load_baseline_profile(path=BASELINE_PROFILE_PATH):
    with open(path) as f:
        return json.load(f)


def load_high_impact_events(conn, event_names=EVENT_NAME_WHITELIST,
                             currencies=EVENT_CURRENCIES):
    """Returns a list of (timestamp_utc_ms, event_name) sorted by timestamp -
    now carries event_name so the caller can look up its release family."""
    name_placeholders = ",".join("?" for _ in event_names)
    currency_placeholders = ",".join("?" for _ in currencies)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT timestamp_utc_ms, event_name FROM calendar_events
        WHERE event_name IN ({name_placeholders})
          AND currency IN ({currency_placeholders})
        ORDER BY timestamp_utc_ms
    """, (*event_names, *currencies))
    return list(cur.fetchall())


def baseline_spread(ts_ms, profile):
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    bucket_minute = (dt.minute // 15) * 15
    key = f"{dt.hour:02d}:{bucket_minute:02d}"
    entry = profile.get(key)
    return entry["mean"] if entry else 0.260


def nearest_event_group(ts_ms, sorted_events):
    """sorted_events: list of (timestamp_utc_ms, event_name), sorted by timestamp.

    Returns (offset_minutes, list_of_event_names) - ALL events sharing the
    nearest timestamp, not just one. Fixes the earlier same-timestamp
    collision bug (e.g. GDP q/q and Core PCE Price Index y/y, which the BEA
    routinely releases together - confirmed happening in real data via
    diagnostics/check_spread_family_scaling.py, 2026-12-23 13:30).
    """
    if not sorted_events:
        return None, []
    timestamps = [e[0] for e in sorted_events]
    idx = bisect.bisect_left(timestamps, ts_ms)
    candidates = []
    if idx < len(sorted_events):
        candidates.append(sorted_events[idx])
    if idx > 0:
        candidates.append(sorted_events[idx - 1])
    if not candidates:
        return None, []

    nearest_ts = min(candidates, key=lambda e: abs(ts_ms - e[0]))[0]

    # Grab every event sharing this exact nearest timestamp, not just one
    left = bisect.bisect_left(timestamps, nearest_ts)
    right = bisect.bisect_right(timestamps, nearest_ts)
    names = [sorted_events[i][1] for i in range(left, right)]

    offset_ms = ts_ms - nearest_ts
    return round(offset_ms / 60000), names


def get_simulated_spread(ts_ms, profile, sorted_events, mode="mean"):
    """
    mode: 'mean' for expected/typical cost simulation (backtesting P&L),
          'worst_case' for stress-testing stop-loss slippage risk.

    Returns (spread, is_event, offset, family). When multiple whitelisted
    events share the same timestamp, `family` reports whichever has the
    LARGEST scale factor - the spread itself uses that same max scale
    factor too, since a risk-facing spread model should reflect the
    stronger of two coinciding effects, not an average that could
    understate real widening.
    """
    base = baseline_spread(ts_ms, profile)
    offset, event_names = nearest_event_group(ts_ms, sorted_events)

    if offset is not None and MIN_OFFSET <= offset <= MAX_OFFSET and event_names:
        families = [RELEASE_FAMILY.get(n, "NFP") for n in event_names]
        scale = max(FAMILY_SCALE_FACTOR.get(f, 1.00) for f in families)
        # For reporting: which family actually drove the max scale
        family = max(families, key=lambda f: FAMILY_SCALE_FACTOR.get(f, 1.00))

        nfp_mean_mult, nfp_max_mult = SPIKE_TEMPLATE[offset]
        scaled_mean_mult = 1 + scale * (nfp_mean_mult - 1)
        scaled_max_mult = 1 + scale * (nfp_max_mult - 1)
        mult = scaled_mean_mult if mode == "mean" else scaled_max_mult
        return round(base * mult, 4), True, offset, family

    return round(base, 4), False, None, None


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    profile = load_baseline_profile()
    events = load_high_impact_events(conn)
    print(f"Loaded {len(events)} whitelisted high-impact ({EVENT_CURRENCIES}) event timestamps "
          f"from {len(EVENT_NAME_WHITELIST)} event types")

    def to_ms(y, m, d, h, mi, s=0):
        return int(datetime(y, m, d, h, mi, s, tzinfo=timezone.utc).timestamp() * 1000)

    test_cases = [
        ("Quiet Tuesday midday",        to_ms(2026, 9, 15, 10, 0, 0)),
        ("Right at NFP release",        to_ms(2026, 9, 4, 12, 30, 5)),
        ("2 min after NFP",             to_ms(2026, 9, 4, 12, 32, 0)),
        ("20 min after NFP (decayed)",  to_ms(2026, 9, 4, 12, 50, 0)),
        ("Daily settlement window",     to_ms(2026, 9, 15, 21, 30, 0)),
    ]

    print(f"\n{'Case':<30} {'Mean spread':<14} {'Worst-case spread':<20} {'Event?':<8} {'Offset':<8} {'Family'}")
    for label, ts in test_cases:
        mean_val, is_event, offset, family = get_simulated_spread(ts, profile, events, mode="mean")
        worst_val, _, _, _ = get_simulated_spread(ts, profile, events, mode="worst_case")
        print(f"{label:<30} {mean_val:<14} {worst_val:<20} {str(is_event):<8} {str(offset):<8} {family}")

    conn.close()