"""
2026 holdout, step 2c: Metrics K and L.

UNLIKE A/C/H/I: K (correlation-regime persistence) and L (lead-lag) are
already self-contained descriptive statistics computed directly on
whatever window you give them - neither is a rolling model that needs
pre-2026 history to seed a window, and neither has a "fit on train" step
to preserve. So the holdout question here is simpler still: re-run the
SAME analysis purely on 2026 and compare the conclusion (contemporaneous-
only relationship for L; regime persistence, not a volatility artifact,
for K) and effect sizes to the original 2021-07-2025-12 findings. This
also means the 2019-2025 database isn't needed for the GOLD side at all -
analytics_2026_holdout.duckdb's minute_bars_ohlc already covers all of
2026 by itself. The ORIGINAL analytics.duckdb IS still needed, but only
for its dxy_m1_ohlc table, which already extends through 2026 in the
production file (confirmed 2026-09-21) - no holdout-side DXY table needed.

CAVEAT: 2026 gives only ~8.7 months = ~26 ten-day blocks for Metric K,
against 101 blocks in the original 4.45-year run. Expect much wider CIs;
a non-significant result here is far more likely to be a power problem
than a real disappearance of the effect - read it that way, not as a
contradiction, unless the point estimate has also reversed sign.

Reuses dxy_alignment_check.py (data loading/on_grid), dxy_metrics_kl.py
(lead-lag and correlation-regime analysis), and dxy_k_vol_control.py (the
volatility-artifact check for K) directly - no reimplementation.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\holdout_2026_kl.py
"""

import os
import sys

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxy_alignment_check as A
import dxy_metrics_kl as M
import dxy_k_vol_control as V

ORIG_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
HOLDOUT_DB = r"C:\Users\opc\gold_ea\data\analytics_2026_holdout.duckdb"


def main(con_orig=None, con_hold=None):
    if con_orig is None:
        con_orig = duckdb.connect(ORIG_DB, read_only=True)
    if con_hold is None:
        con_hold = duckdb.connect(HOLDOUT_DB, read_only=True)
    for c in (con_orig, con_hold):
        c.execute("SET TimeZone='UTC'")

    gold = A.load_minute_close(con_hold, A.GOLD_TABLE, "minute_ts")     # all-2026 gold, from the holdout file
    dxy_ts = A.discover_ts_col(con_orig, A.DXY_TABLE)
    dxy = A.load_minute_close(con_orig, A.DXY_TABLE, dxy_ts)            # full DXY history, already covers 2026

    start, end = max(gold.index.min(), dxy.index.min()), min(gold.index.max(), dxy.index.max())
    print(f"2026 holdout window (gold-DXY overlap): {start} -> {end}  ({(end - start).days / 30.4:.1f} months)")
    gold_g, dxy_g = A.on_grid(gold, start, end), A.on_grid(dxy, start, end)

    print("\n" + "=" * 90)
    print("METRIC L HOLDOUT - lead-lag (1-minute returns), 2026 only")
    print("=" * 90)
    print("(2021-2025 reference: rho(0)=-0.379 overall/-0.658 in the NY release window; no exploitable lag)")
    M.report_lead_lag(M.lead_lag(gold_g, dxy_g))

    print("\n" + "=" * 90)
    print("METRIC K HOLDOUT - correlation-regime persistence (hourly returns), 2026 only")
    print("=" * 90)
    print("(2021-2025 reference: persistence +0.648 [+0.47,+0.77], 101 blocks; survived vol-control at +0.606)")
    M.correlation_regimes(gold_g, dxy_g)

    print("\n" + "-" * 90)
    print("Volatility-control check (is 2026's persistence just a volatility artifact? - see dxy_k_vol_control.py)")
    print("-" * 90)
    bt = V.block_table(gold_g, dxy_g)
    V.analyse(bt)


if __name__ == "__main__":
    main()