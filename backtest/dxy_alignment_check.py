"""
DXY / gold timestamp alignment check - run BEFORE building Metrics K and L.

WHY: gold minute bars come from Dukascopy (UTC). The DXY minute bars were
pulled through MetaTrader 5, whose timestamps are usually BROKER SERVER TIME
(often UTC+2 in winter / UTC+3 in summer, switching on US DST dates) unless
the pipeline converted them. A constant or DST-shifting offset of even a few
minutes silently ruins lead-lag results, and an offset of hours dilutes
correlation-regime results. This script measures the offset from the data.

TWO INDEPENDENT CHECKS
  A. Cross-correlation scan: correlation between gold's 5-minute return at
     time t and DXY's 5-minute return at time t+k, over a grid of lags k
     (minutes). Gold and the dollar move inversely, so the correlation should
     be most NEGATIVE at the lag where the clocks agree.
       peak at k = 0      -> feeds aligned
       peak at k = +120   -> DXY timestamps are 120 minutes AHEAD of UTC
                             (e.g. server time UTC+2); correct by subtracting
                             120 minutes from the DXY timestamps.
     Run for all data, and separately for winter (Dec-Feb) and summer (Jun-Aug):
     a DIFFERENT peak lag in summer vs winter means the DXY clock follows a
     local/server DST rule and needs a DST-aware conversion, not a constant.
  B. Event-timing histogram: for each weekday, the UTC minute of the largest
     absolute 1-minute return between 11:30 and 15:30 UTC (this window contains
     the 08:30 New York data releases). Expected peak: 13:30 UTC in winter,
     12:30 UTC in summer. Compare gold vs DXY: if DXY's peak minutes sit at
     a different clock time, that is the offset.

If the peak lag is not 0, do NOT run Metrics K/L until the DXY timestamps are
corrected in the database (or an explicit offset is applied everywhere).

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\dxy_alignment_check.py
"""

import numpy as np
import pandas as pd
import duckdb

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
GOLD_TABLE = "minute_bars_ohlc"
DXY_TABLE = "dxy_m1_ohlc"

RET_WINDOW = 5
FINE_LAGS = list(range(-10, 11))
COARSE_LAGS = [-240, -210, -180, -150, -120, -90, -60, -30, 30, 60, 90, 120, 150, 180, 210, 240]
LAGS = sorted(set(FINE_LAGS + COARSE_LAGS))
SEASONS = {"all": None, "winter (Dec-Feb)": [12, 1, 2], "summer (Jun-Aug)": [6, 7, 8]}
EVENT_WINDOW = (11 * 60 + 30, 15 * 60 + 30)   # UTC minute-of-day
EVENT_SEASONS = {"winter (Dec-Feb)": [12, 1, 2], "summer (Jun-Aug)": [6, 7, 8]}


def to_naive_utc(ts):
    ts = pd.to_datetime(ts)
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    return ts


def load_minute_close(con, table, ts_col, close_col="close"):
    df = con.execute(f"SELECT {ts_col} AS ts, {close_col} AS c FROM {table} WHERE {close_col} IS NOT NULL ORDER BY {ts_col}").fetchdf()
    if pd.api.types.is_integer_dtype(df["ts"]):
        df["ts"] = pd.to_datetime(df["ts"], unit="s" if df["ts"].iloc[0] < 4e10 else "ms")
    else:
        df["ts"] = to_naive_utc(df["ts"])
    s = df.drop_duplicates("ts").set_index("ts")["c"].astype(float)
    return s


def discover_ts_col(con, table):
    cols = con.execute(f"DESCRIBE {table}").fetchall()
    print(f"{table} columns: {[(c[0], c[1]) for c in cols]}")
    for c in cols:
        if "TIMESTAMP" in c[1].upper():
            return c[0]
    for c in cols:
        if any(k in c[0].lower() for k in ("time", "ts", "date")):
            return c[0]
    raise RuntimeError(f"cannot find a timestamp column in {table}")


def on_grid(s, start, end):
    idx = pd.date_range(start, end, freq="min")
    return s.reindex(idx)


def lag_scan(gold_r, dxy_r, months=None):
    """corr(gold_r[t], dxy_r[t+k]) for each lag k; optional month filter."""
    if months is not None:
        m = gold_r.index.month.isin(months)
    else:
        m = np.ones(len(gold_r), dtype=bool)
    out = {}
    g = gold_r[m]
    for k in LAGS:
        d = dxy_r.shift(-k).reindex(g.index)
        out[k] = g.corr(d)
    return pd.Series(out)


def event_minute_hist(close_1m, months):
    r = np.log(close_1m).diff().abs().dropna()      # close_1m is on the minute grid (NaN = missing),
    r = r[r.index.month.isin(months)]                # so only true consecutive-minute returns remain
    mod = r.index.hour * 60 + r.index.minute
    win = r[(mod >= EVENT_WINDOW[0]) & (mod < EVENT_WINDOW[1]) & (r.index.dayofweek < 5)]
    if len(win) == 0:
        return pd.Series(dtype=int)
    peak_ts = pd.DatetimeIndex(win.groupby(win.index.normalize()).idxmax().values)
    minutes = pd.Series(peak_ts.hour * 60 + peak_ts.minute)
    return minutes.value_counts()


def fmt_min(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def main(con=None):
    if con is None:
        con = duckdb.connect(ANALYTICS_DB, read_only=True)
    dxy_ts = discover_ts_col(con, DXY_TABLE)
    gold = load_minute_close(con, GOLD_TABLE, "minute_ts")
    dxy = load_minute_close(con, DXY_TABLE, dxy_ts)
    print(f"gold minutes: {len(gold):,}  {gold.index.min()} -> {gold.index.max()}")
    print(f"DXY  minutes: {len(dxy):,}  {dxy.index.min()} -> {dxy.index.max()}")
    start, end = max(gold.index.min(), dxy.index.min()), min(gold.index.max(), dxy.index.max())
    gold_g, dxy_g = on_grid(gold, start, end), on_grid(dxy, start, end)
    print(f"overlap: {start} -> {end}   gold present {gold_g.notna().mean():.1%} of minutes, DXY {dxy_g.notna().mean():.1%}")

    gr = np.log(gold_g).diff(RET_WINDOW)
    dr = np.log(dxy_g).diff(RET_WINDOW)

    print("\n" + "=" * 78)
    print("A. Cross-correlation scan: corr(gold 5-min return at t, DXY 5-min return at t+k)")
    print("   most NEGATIVE correlation = the lag where the clocks agree (k=0 means aligned)")
    print("=" * 78)
    scans = {}
    for name, months in SEASONS.items():
        cc = lag_scan(gr, dr, months)
        scans[name] = cc
        best = cc.idxmin()
        top = cc.sort_values().head(3)
        print(f"\n{name}: peak (most negative) at k = {best:+d} min, corr = {cc[best]:+.3f}")
        print("   top 3 lags: " + ", ".join(f"{k:+d}:{v:+.3f}" for k, v in top.items()))
        print("   fine profile k=-5..+5: " + " ".join(f"{k:+d}:{cc[k]:+.3f}" for k in range(-5, 6)))
    b_w, b_s = scans["winter (Dec-Feb)"].idxmin(), scans["summer (Jun-Aug)"].idxmin()
    print("\nVERDICT (A):")
    if scans["all"].idxmin() == 0 and b_w == 0 and b_s == 0:
        print("  peak at k=0 in all, winter and summer: feeds appear aligned (still check B).")
    elif b_w == b_s:
        print(f"  peak at k={b_w:+d} min in both seasons: constant offset -> DXY timestamps are {b_w:+d} min from UTC; subtract {b_w} min.")
    else:
        print(f"  winter peak {b_w:+d}, summer peak {b_s:+d}: OFFSET CHANGES WITH SEASON -> DXY clock follows a DST-shifting server time.")
        print("  Needs a DST-aware correction, not a constant. Do not run K/L until fixed.")

    print("\n" + "=" * 78)
    print("B. Event-timing histogram: UTC minute of largest |1-min return| in 11:30-15:30, per weekday")
    print("   expected peak ~13:30 winter / ~12:30 summer (08:30 New York releases)")
    print("=" * 78)
    for name, months in EVENT_SEASONS.items():
        hg, hd = event_minute_hist(gold_g, months), event_minute_hist(dxy_g, months)
        print(f"\n{name}:")
        print("   gold top minutes: " + ", ".join(f"{fmt_min(m)}x{c}" for m, c in hg.head(4).items()))
        print("   DXY  top minutes: " + ", ".join(f"{fmt_min(m)}x{c}" for m, c in hd.head(4).items()))
    print("\nIf gold peaks at 13:30/12:30 but DXY peaks hours earlier/later, the DXY clock is shifted by that amount.")


if __name__ == "__main__":
    main()