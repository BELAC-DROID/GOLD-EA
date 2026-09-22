"""
Metric C re-test (v3): volatility regime classification, session level.

Same question as volatility_regime_classification.py (does yesterday's
session-volatility regime predict today's, vs the majority baseline?), now
scored with the upgraded regime_transition_harness.py:
  * effect size (% Brier gain over majority) + block-bootstrap 95% CI
  * verdict codes: '+' significant AND >=1% gain, 't' significant but
    trivial (<1%), '0' no detectable effect, '-' significantly worse
  * London/NY run under BOTH session definitions (fixed UTC hours vs
    DST-aware local hours), reusing the helpers from
    range_prediction_v3_baselines.py. Asian stays fixed UTC (Tokyo: no DST).

Labelling is unchanged from v2 of Metric C: today's session range / prior
close is ranked against the previous LOOKBACK sessions of the same session
(20th/80th percentile -> low/normal/high); prior_regime = yesterday's label.
Lookbacks 60/100/150 are kept as the sensitivity dimension.

The 6 window combos overlap heavily: read them as robustness to window
choice, not as 6 independent tests. block_len=20 (~1 month of sessions).

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\volatility_regime_classification_v3.py
Output: compact console summary + volatility_regime_classification_v3_results.csv
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regime_transition_harness as H
import range_prediction_v3_baselines as R   # reuse SQL helpers (main() is guarded)

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
LOOKBACKS = [60, 100, 150]
LOW_PCTL, HIGH_PCTL = 20, 80
REGIMES = ["low", "normal", "high"]
BLOCK_LEN = 20


def label_regimes(df, lookback):
    ratios = df["ratio"].values
    regimes = [None] * len(ratios)
    for i in range(lookback, len(ratios)):
        window = ratios[i - lookback:i]
        lo, hi = np.percentile(window, [LOW_PCTL, HIGH_PCTL])
        regimes[i] = "low" if ratios[i] < lo else ("high" if ratios[i] > hi else "normal")
    out = df.copy()
    out["regime"] = regimes
    out["prior_regime"] = out["regime"].shift(1)
    return out.dropna(subset=["regime", "prior_regime"])


def main():
    con = duckdb.connect(ANALYTICS_DB, read_only=True)
    con.execute("SET TimeZone='UTC'")
    prior = R.prior_close_table(con)

    jobs = [("asian", "fixed_utc", R.session_ranges_fixed(con, *R.FIXED_SESSIONS["asian"]))]
    for name in ["london", "ny"]:
        jobs.append((name, "fixed_utc", R.session_ranges_fixed(con, *R.FIXED_SESSIONS[name])))
        sh, eh, tz = R.DST_SESSIONS[name]
        jobs.append((name, "dst_aware", R.session_ranges_dst(con, sh, eh, tz)))

    rows, summary = [], []
    for name, mode, ranges in jobs:
        raw = ranges.merge(prior, on="day", how="inner").sort_values("day").reset_index(drop=True)
        raw["ratio"] = raw["day_range"] / raw["prior_close"]
        print(f"\n{'=' * 78}\n{name.upper()} | {mode} | sessions={len(raw)}")
        for lb in LOOKBACKS:
            df = label_regimes(raw, lb)
            res = H.run_all_combos_detailed(df, REGIMES, f"{name}/{mode}/lb{lb}",
                                            block_len=BLOCK_LEN, verbose=False)
            codes = "".join(r["code"] for r in res)
            gain = float(np.mean([r["gain_pct"] for r in res])) if res else float("nan")
            print(f"  lookback={lb:3d}  combos[{'|'.join(codes)}]  mean gain vs majority {gain:+.2f}%")
            summary.append((name, mode, lb, "|".join(codes), gain))
            for r in res:
                rows.append({"session": name, "mode": mode, "lookback": lb, **r})

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "volatility_regime_classification_v3_results.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\n{'=' * 78}\nSUMMARY (combo order: {' | '.join(c['name'] for c in H.COMBOS)})")
    print(f"  '+' sig & >= {H.MIN_MATERIAL_GAIN_PCT:g}% gain | 't' sig but trivial | '0' none | '-' sig worse")
    print(f"{'session':8s} {'mode':10s} {'lookback':>8s} {'combos':>15s} {'mean gain %':>12s}")
    for name, mode, lb, codes, g in summary:
        print(f"{name:8s} {mode:10s} {lb:8d} {codes:>15s} {g:+12.2f}")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()