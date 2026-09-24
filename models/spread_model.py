"""
Exness-realistic spread simulation model for XAU/USD backtesting.

Combines:
  1. A flat time-of-day baseline (from normal_day_spread_profile.json).
  2. An event-driven spike/decay overlay, scaled per release family.

UPDATE 2 (2026-09-21) - direct spread validation, closing the assumption
flagged in UPDATE 1 below. backtest/spread_model_validation.py measured
REAL Exness spread (source='exness_live', 2026-01 to 2026-09) around every
whitelisted release in that window, instead of relying on Metric J's PRICE-
magnitude ratios as a stand-in. Two changes came out of it:

  (a) SPIKE_TEMPLATE's MEAN column was recalibrated from 8 real NFP events,
      not the single Sept 4 event. That one event turned out to be an
      outlier: its own peak multiplier (1.96x) sat above the top of the
      8-event 95% CI (1.30-1.90x), and the decay tail (offsets 6-8) runs a
      bit longer than the old template assumed (observed ~1.04-1.05x vs
      template's ~1.01x, CIs not overlapping). The MAX (worst_case) column
      was left at whichever is larger, the old value or the worst single
      tick actually observed across those 8 events (a "never get less
      conservative" rule) - the old Sept-4-derived max was already close
      to the observed worst case at most offsets (it WAS the single
      worst-observed event before this update), so most max values are
      unchanged; two offsets got a small upward revision. n=8 is still a
      small sample for a worst-case figure - revisit as more NFP events
      accumulate, don't treat the max column as final.

  (b) FAMILY_SCALE_FACTOR: CPI (0.91) and FOMC (0.74) were confirmed close
      to their old price-magnitude-derived values (0.90, 0.69) and updated
      to the directly-measured spread figures. GDP and PCE could NOT be
      validated as separate families: the calendar data shows Core PCE
      Price Index m/m and y/y co-release with GDP q/q at the exact same
      timestamp in ~89% of instances (confirmed by the BEA's own release
      schedule) - spread_model.py's own same-timestamp collision handling
      (nearest_event_group, below) already assigns these to whichever name
      has the larger scale factor, so "GDP" events in this dataset were
      already mostly a blended GDP+PCE effect, not pure GDP, and pure PCE
      only occurred once in this window (not enough to estimate on its
      own). Rather than keep two separate constants where one is
      contaminated by the other and the other is nearly unmeasurable, GDP
      and PCE are merged into one honestly-labeled family, GDP_PCE, scale
      0.28 (the measured blended figure). If a future calendar or release
      schedule change causes GDP and PCE to reliably occur independently,
      re-run spread_model_validation.py and consider splitting them again.

UPDATE 1 (prior): Metric J (catalyst magnitude prediction, Phase 3) tested
whether NFP's spike shape generalizes to the other release families using
PRICE-magnitude ratios (NFP 0.365% of price, CPI 0.328%, FOMC 0.253%, GDP
0.150%, PCE 0.124%) as a proxy for spread widening, since no one had
directly measured Exness spread behavior around those releases. UPDATE 2
above replaces that proxy with direct measurement; the price-magnitude
ratios are kept here for the history but are no longer what
FAMILY_SCALE_FACTOR is built from.

ORIGINAL LIMITATION (addressed by UPDATE 2's (a) above, kept for history):
the base spike shape (offsets -1 to +8, "shock then decay") was originally
derived from exactly ONE observed event - the Sept 4, 2026 NFP release -
applied uniformly to every event type, then later scaled by family via the
price-magnitude proxy in UPDATE 1. The MEAN column is now an 8-event
average; the MAX column is still driven by a small sample (see (a) above).
"""

import sqlite3
import json
import bisect
from datetime import datetime, timezone

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"
BASELINE_PROFILE_PATH = r"C:\Users\opc\gold_ea\data\normal_day_spread_profile.json"

# Minute offset relative to event time -> (mean_multiplier, max_multiplier).
# MEAN column: recalibrated 2026-09-21 from 8 real NFP events in
# ticks(source='exness_live'), replacing the single-event Sept 4 figures
# (see backtest/spread_model_validation.py, Q1). MAX column: max(old value,
# worst single tick observed across those 8 events) - see UPDATE 2(a) above.
# Per-family scaling is applied on top of this at lookup time, not baked in.
SPIKE_TEMPLATE = {
    -1: (0.948, 2.310),
     0: (1.577, 7.690),
     1: (1.229, 2.230),
     2: (1.112, 2.230),
     3: (1.102, 2.230),
     4: (1.065, 2.230),
     5: (1.054, 1.390),
     6: (1.050, 1.390),
     7: (1.043, 1.390),
     8: (1.047, 1.390),
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
#
# GDP q/q and both Core PCE Price Index names now map to the SAME family,
# "GDP_PCE" (2026-09-21) - see UPDATE 2(b) above. They were kept separate
# in catalyst_magnitude_prediction.py's own PRICE-magnitude analysis (that
# script measures price moves per event NAME, which is still meaningful
# even when two names share a timestamp); it is specifically the SPREAD
# scale factor below where keeping them separate was misleading, since one
# was almost always measuring the other's effect too.
RELEASE_FAMILY = {
    "Nonfarm Payrolls": "NFP",
    "CPI": "CPI", "CPI y/y": "CPI", "CPI m/m": "CPI",
    "Core CPI m/m": "CPI", "Core CPI n.s.a. m/m": "CPI",
    "Core PCE Price Index m/m": "GDP_PCE", "Core PCE Price Index y/y": "GDP_PCE",
    "FOMC Statement": "FOMC", "FOMC Press Conference": "FOMC",
    "GDP q/q": "GDP_PCE",
}

# Per-family scale factor applied to the (multiplier - 1) excess over
# baseline. Recalibrated 2026-09-21 from directly-measured spread widening
# (backtest/spread_model_validation.py, Q2), replacing the original
# PRICE-magnitude-derived values (NFP 1.00, CPI 0.90, FOMC 0.69, GDP 0.41,
# PCE 0.34 - see UPDATE 1 above for how those were derived).
#   NFP: 1.00 (reference, by construction - the template itself is NFP's own shape)
#   CPI: 0.91 (measured; old price-magnitude estimate was 0.90 - confirmed)
#   FOMC: 0.74 (measured; old estimate was 0.69 - close, small upward revision)
#   GDP_PCE: 0.28 (measured blended GDP+PCE figure - see UPDATE 2(b); n=9
#     anchors, 89% of which were an actual GDP+PCE co-release, so this
#     number describes that combined event, not GDP or PCE in isolation)
FAMILY_SCALE_FACTOR = {
    "NFP": 1.00,
    "CPI": 0.91,
    "FOMC": 0.74,
    "GDP_PCE": 0.28,
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
    diagnostics/check_spread_family_scaling.py, 2026-12-23 13:30, and again
    via spread_model_validation.py's event diagnostics, 2026-09-21, in ~89%
    of GDP q/q occurrences).

    NOTE (2026-09-21): since GDP q/q and both Core PCE Price Index names now
    map to the same family (GDP_PCE, see RELEASE_FAMILY above), this
    specific collision no longer needs the max-scale tie-break below to
    produce a sensible answer - both names resolve to the same family and
    scale regardless of which one "wins". The tie-break logic is kept
    general, since some other coincidental collision (e.g. an unscheduled
    calendar overlap between families not designed to co-release) could
    still occur and needs a defined behavior.
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
    understate real widening. As of 2026-09-21 this only matters for a
    collision between families that don't already share one (see
    RELEASE_FAMILY note above) - GDP q/q and Core PCE Price Index events no
    longer need this tie-break to reach the right family.
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