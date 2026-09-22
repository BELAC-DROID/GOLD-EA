"""
Compare two tick snapshots (e.g. one captured on a demo account, one on
a live account) from capture_tick_snapshot.py, covering the SAME UTC
window, to check whether Exness demo spread behavior matches live.

Usage:
  python compare_spread_snapshots.py <file_a.csv> <file_b.csv> [event_utc_iso]

event_utc_iso (optional): an ISO timestamp (e.g. 2026-09-22T08:30:00)
for a scheduled release inside the window - the comparison then also
reports spread specifically around it, which is where demo/live
divergence is most likely to show, if it exists at all.
"""

import sys

import numpy as np
import pandas as pd


def load(path):
    df = pd.read_csv(path)
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True, format="ISO8601")
    return df.sort_values("time_utc").reset_index(drop=True)


def summarize(df, label):
    s = df["spread_price"]
    print(f"\n{label}: n_ticks={len(df):,}  window {df['time_utc'].min()} -> {df['time_utc'].max()}")
    print(f"  spread mean={s.mean():.4f}  median={s.median():.4f}  "
          f"p90={s.quantile(0.9):.4f}  max={s.max():.4f}  min={s.min():.4f}")


def bucketed_compare(a, b, freq="1min"):
    sa = a.set_index("time_utc")["spread_price"].resample(freq).median()
    sb = b.set_index("time_utc")["spread_price"].resample(freq).median()
    both = pd.concat([sa, sb], axis=1, keys=["a", "b"]).dropna()
    if len(both) == 0:
        print("  No overlapping time buckets - check both files cover the same window/day.")
        return both
    both["diff"] = both["b"] - both["a"]
    both["ratio"] = both["b"] / both["a"].replace(0, np.nan)
    return both


def event_window_compare(both, event_ts, pre_min=2, post_min=15):
    event_ts = pd.Timestamp(event_ts, tz="UTC")
    win = both[(both.index >= event_ts - pd.Timedelta(minutes=pre_min)) &
               (both.index <= event_ts + pd.Timedelta(minutes=post_min))]
    if win.empty:
        print("  Event window not covered by this data - check event_utc_iso and the capture window.")
        return
    print(f"\nAround event {event_ts} (-{pre_min}min to +{post_min}min), per-minute median spread:")
    print(win.to_string(float_format=lambda v: f"{v:.4f}"))
    ra, rb = win["a"].mean(), win["b"].mean()
    print(f"\n  mean spread in event window: a={ra:.4f}  b={rb:.4f}  ratio b/a={rb / ra:.2f}x"
          if ra else "  a-mean is 0, cannot compute ratio")


def main():
    if len(sys.argv) < 3:
        print("Usage: python compare_spread_snapshots.py <file_a.csv> <file_b.csv> [event_utc_iso]")
        sys.exit(1)
    path_a, path_b = sys.argv[1], sys.argv[2]
    event_ts = sys.argv[3] if len(sys.argv) > 3 else None

    a, b = load(path_a), load(path_b)
    summarize(a, f"A ({path_a})")
    summarize(b, f"B ({path_b})")

    print("\n" + "=" * 70)
    print("Per-minute median spread comparison (B vs A)")
    print("=" * 70)
    both = bucketed_compare(a, b)
    if len(both):
        print(f"\noverall: mean(A)={both['a'].mean():.4f}  mean(B)={both['b'].mean():.4f}  "
              f"mean ratio B/A={both['ratio'].mean():.2f}  corr(A,B)={both['a'].corr(both['b']):.3f}")
        top = both.reindex(both["diff"].abs().sort_values(ascending=False).index[:5])
        print("biggest 5 absolute differences (B-A):")
        print(top.to_string(float_format=lambda v: f"{v:.4f}"))
        if event_ts:
            event_window_compare(both, event_ts)

    print("\nHow to read this:")
    print("  - Mean ratio B/A close to 1.0 and high correlation: demo and live spread behavior")
    print("    match closely - existing demo-account data is trustworthy for spread work.")
    print("  - Diverging (especially around a news event, if you passed one): the spread side")
    print("    of the dataset (baseline profile, SPIKE_TEMPLATE, Metric J validation) needs to")
    print("    be rebuilt from LIVE-account ticks, not demo.")


if __name__ == "__main__":
    main()