import sqlite3
import MetaTrader5 as mt5
from datetime import datetime, timezone

SYMBOL = "XAUUSDm"

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error())
    quit()

# Diagnostic: confirm we actually have a live terminal + account connection
# before trying to pull anything. If either of these prints None, the
# problem is the terminal connection itself, not the symbol or date range.
info = mt5.terminal_info()
print("Terminal info:", info)
account = mt5.account_info()
print("Account info:", account)

if info is None or account is None:
    print("No live terminal/account connection - open MT5 on the VM desktop, log into Exness, then rerun.")
    mt5.shutdown()
    quit()

# Make sure the symbol is selected/visible in Market Watch, or copy_ticks_range
# can silently return nothing even when the symbol exists.
if not mt5.symbol_select(SYMBOL, True):
    print(f"Failed to select {SYMBOL}:", mt5.last_error())
    mt5.shutdown()
    quit()

conn = sqlite3.connect(r"C:\Users\opc\gold_ea\data\gold_data.db")
cur = conn.cursor()

def pull_range(label, dt_from, dt_to):
    print(f"Pulling {label}: {dt_from} -> {dt_to}")
    ticks = mt5.copy_ticks_range(SYMBOL, dt_from, dt_to, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        print(f"  No ticks returned for {label}. Error:", mt5.last_error())
        return 0

    rows = [
        (
            SYMBOL,
            int(t["time_msc"]),
            float(t["bid"]),
            float(t["ask"]),
            "exness",
        )
        for t in ticks
    ]

    cur.executemany(
        "INSERT INTO ticks (symbol, timestamp_utc_ms, bid, ask, source) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    print(f"  Inserted {len(rows)} rows for {label}")
    return len(rows)

# This week: Sept 14-18, 2026 (Mon-Fri), full sessions
week_from = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
week_to   = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)  # exclusive end, covers through Fri close
pull_range("Sept 14-18 (this week)", week_from, week_to)

# NFP day: Sept 4, 2026 (widen a bit either side to catch pre/post volatility)
nfp_from = datetime(2026, 9, 3, 18, 0, tzinfo=timezone.utc)
nfp_to   = datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc)
pull_range("Sept 4 NFP window", nfp_from, nfp_to)

conn.close()
mt5.shutdown()
print("Done.")