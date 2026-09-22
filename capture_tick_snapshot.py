"""
Capture a labeled tick snapshot (bid/ask/spread) from whichever Exness
account is currently logged into the running MT5 terminal - used to
compare DEMO vs LIVE spread behavior over the SAME historical window.

USAGE
  1. Log into your Exness DEMO account in the MT5 terminal.
  2. Edit WINDOW_START / WINDOW_END below to a UTC window you want to
     compare. Recommended: pick a window covering a scheduled
     high-impact release (e.g. 08:00-09:30 UTC on an NFP/CPI day) so
     you see both the quiet baseline AND a spike - a shared "cached
     market data" feed, if that's what's happening, would tend to look
     most similar in quiet periods and most different at a real spike,
     so a quiet-only window is the less informative test.
  3. Run: python capture_tick_snapshot.py
     -> writes tick_snapshot_demo_<login>_<window>.csv
  4. Log OUT of demo, log INTO your LIVE account in the same terminal.
  5. Run the script again, unchanged (edit nothing).
     -> writes tick_snapshot_real_<login>_<window>.csv
  6. Run compare_spread_snapshots.py on the two output files.

This pulls ticks by TIME RANGE (mt5.copy_ticks_range), not by watching
live ticks as they happen - both runs ask the server for the same
historical window, so you do NOT need both accounts connected at once.
This assumes the MT5 server actually serves account-specific tick
history for a past window; if it doesn't, both files will look
identical regardless of any live spread difference, which is itself
useful information (means the divergence, if any, only shows up on
truly live/streaming ticks - a harder thing to check, ask if you hit
this).
"""

import os
import sys
from datetime import datetime, timezone

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    print("MetaTrader5 package not found. Install with: pip install MetaTrader5")
    sys.exit(1)

# ---- EDIT THESE before each run ----
WINDOW_START = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
WINDOW_END   = datetime(2026, 9, 4, 13, 30, 0, tzinfo=timezone.utc)
SYMBOL_HINT = "XAUUSDm"   # searches for the closest matching symbol name on this account
OUTPUT_DIR = r"C:\Users\opc\gold_ea\data\spread_check"
# -------------------------------------

TRADE_MODE_NAMES = {0: "demo", 1: "contest", 2: "real"}


def find_symbol(hint):
    syms = mt5.symbols_get()
    if not syms:
        return None
    matches = [s.name for s in syms if hint.upper() in s.name.upper()]
    if not matches:
        return None
    exact = [m for m in matches if m.upper() == hint.upper()]
    return exact[0] if exact else min(matches, key=len)


def main():
    if not mt5.initialize():
        print("mt5.initialize() failed:", mt5.last_error())
        sys.exit(1)

    acc = mt5.account_info()
    if acc is None:
        print("Could not read account info - are you logged in to the terminal?", mt5.last_error())
        mt5.shutdown()
        sys.exit(1)

    mode = TRADE_MODE_NAMES.get(acc.trade_mode, f"unknown{acc.trade_mode}")
    print(f"Logged in: login={acc.login}  server={acc.server}  trade_mode={mode}  balance={acc.balance}")

    symbol = find_symbol(SYMBOL_HINT)
    if symbol is None:
        print(f"No symbol matching '{SYMBOL_HINT}' found on this account's Market Watch. "
              f"Try SYMBOL_HINT='XAU', or check the exact name in MT5.")
        mt5.shutdown()
        sys.exit(1)
    mt5.symbol_select(symbol, True)
    print(f"Using symbol: {symbol}")

    ticks = mt5.copy_ticks_range(symbol, WINDOW_START, WINDOW_END, mt5.COPY_TICKS_ALL)
    mt5.shutdown()

    if ticks is None or len(ticks) == 0:
        print("No ticks returned for this window. Possible causes: window too far back for "
              "this server's tick history retention, market closed for that window, or wrong symbol.")
        sys.exit(1)

    df = pd.DataFrame(ticks)
    df["time_utc"] = pd.to_datetime(df["time_msc"], unit="ms", utc=True)
    df["spread_price"] = df["ask"] - df["bid"]
    keep = [c for c in ["time_utc", "bid", "ask", "spread_price", "last", "volume", "flags"] if c in df.columns]
    df = df[keep]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tag = f"{WINDOW_START:%Y%m%d_%H%M}_{WINDOW_END:%H%M}"
    out_path = os.path.join(OUTPUT_DIR, f"tick_snapshot_{mode}_{acc.login}_{tag}.csv")
    df.to_csv(out_path, index=False)

    print(f"\nSaved {len(df):,} ticks -> {out_path}")
    print(f"Spread (price units) over this window: mean={df['spread_price'].mean():.4f}  "
          f"median={df['spread_price'].median():.4f}  max={df['spread_price'].max():.4f}")
    print("\nNext: log into the OTHER account type, re-run this script unchanged (same window), "
          "then run compare_spread_snapshots.py on the two output files.")


if __name__ == "__main__":
    main()