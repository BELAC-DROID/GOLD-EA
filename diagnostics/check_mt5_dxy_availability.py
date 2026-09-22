"""
Check what MT5 offers for a US Dollar Index (DXY) symbol, before deciding
whether to source DXY data externally. If MT5 has a usable symbol, this
reuses the exact same Python<->MT5 pipeline already built for XAUUSDm,
rather than standing up a new external data source.

Checks common symbol names brokers use for the dollar index, and for
whichever ones exist, reports available history range and what
timeframes MT5 will actually return data for - since Metric L (lead-lag)
needs intraday resolution to be meaningful, while Metric K (correlation
regime) would likely be fine with daily.
"""

import MetaTrader5 as mt5
from datetime import datetime, timezone

if not mt5.initialize():
    print("MT5 initialize() failed:", mt5.last_error())
    raise SystemExit

CANDIDATE_NAMES = [
    "USDX", "DXY", "DX", "USDIDX", "USDIndex", "US30USD",  # last one deliberately wrong, sanity check
    "USDollarIndex", "DXYm", "DX-Y.NYB",
]

print("Symbols matching common DXY names (checking mt5.symbols_get with wildcards):\n")
all_symbols = mt5.symbols_get()
matches = [s.name for s in all_symbols if "usd" in s.name.lower() and (
    "idx" in s.name.lower() or "dx" in s.name.lower() or "index" in s.name.lower()
)]
print(f"Broad wildcard matches ({len(matches)}):")
for name in matches:
    print(f"  {name}")

print(f"\nChecking specific candidate names directly:")
found = []
for name in CANDIDATE_NAMES:
    info = mt5.symbol_info(name)
    if info is not None:
        found.append(name)
        print(f"  FOUND: {name}")
    else:
        print(f"  not found: {name}")

print(f"\n{'='*70}")
if not found and not matches:
    print("No DXY-like symbol found on this MT5/Exness account.")
    print("Next step would be an external source (Yahoo Finance, FRED, or a data vendor).")
else:
    candidates_to_check = found + [m for m in matches if m not in found]
    for name in candidates_to_check:
        print(f"\n--- {name} ---")
        info = mt5.symbol_info(name)
        print(f"  description: {info.description}")

        # Check how far back D1 (daily) data goes
        rates_d1 = mt5.copy_rates_range(
            name, mt5.TIMEFRAME_D1,
            datetime(2019, 1, 1, tzinfo=timezone.utc),
            datetime.now(timezone.utc)
        )
        if rates_d1 is not None and len(rates_d1) > 0:
            print(f"  D1 (daily) bars available: {len(rates_d1)}, "
                  f"from {datetime.fromtimestamp(rates_d1[0]['time'], tz=timezone.utc).date()} "
                  f"to {datetime.fromtimestamp(rates_d1[-1]['time'], tz=timezone.utc).date()}")
        else:
            print("  D1 data: none returned")

        # Check if M1 (intraday) data exists at all, over a short recent window
        rates_m1 = mt5.copy_rates_range(
            name, mt5.TIMEFRAME_M1,
            datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
            datetime.now(timezone.utc)
        )
        if rates_m1 is not None and len(rates_m1) > 0:
            print(f"  M1 (intraday) bars available today: {len(rates_m1)} - intraday resolution confirmed usable")
        else:
            print("  M1 data: none returned today - may not support intraday, or market currently closed")

mt5.shutdown()