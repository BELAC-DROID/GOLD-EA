"""
Metric D replacement (v3): does "trend character" persist?  (replaces the
Hurst / R-S classification in hurst_trend_classification.py)

WHY THE OLD METRIC D WAS DROPPED (evidence from simulation, 2026-09-21):
  1. Its 60-day windows overlap its 20-day-stride comparison windows by 40 of
     60 days, so labels persist by construction. On PURE iid noise (t(4)
     returns, same labelling, same scoring) the "transition model beats
     majority" by +5.9% on average (range -0.9% to +13%) at stride 20, vs a
     real-data range of about -0.5% to +5.4%: the real results are inside the
     noise band. At stride 60 (no overlap) the noise gain is -3.1%.
  2. Its estimator is a single-scale R/S ratio, log(R/S)/log(n), on n=60
     returns. It is weakly discriminating: iid noise is labelled 'trending'
     ~30% / 'mean_reverting' ~11% of the time (close to the label mix seen on
     real gold), AR(+0.2) only 54% trending, AR(-0.2) only 28% mean-reverting.
  3. With 60-day windows there are only ~30 NON-overlapping windows in 7 years
     of daily data, far too few to test persistence.

WHAT THIS DOES INSTEAD (more data, unbiased-centred statistic, honest null):
  * Uses intraday bars (H1 and M30), where 7 years give ~170 non-overlapping
    blocks of ~10 trading days each, instead of ~30.
  * Trend character per block = Lo-MacKinlay heteroskedasticity-robust
    variance-ratio z-statistic VR(q) (H1: q=4 bars = 4h; M30: q=8 bars = 4h).
    Null-centred at 0 for a random walk; z>0 trending, z<0 mean-reverting.
    Returns that span weekends/holidays/long gaps are dropped.
  * Persistence = Spearman rank correlation between the z of consecutive
    NON-overlapping blocks (no shared data by construction), with a
    block-bootstrap 95% CI, and a p-value from a within-block permutation null
    (shuffling returns inside each block keeps every block's volatility level
    but destroys serial dependence, so it isolates trend-character persistence
    from volatility clustering).
  * Also reported: first-half vs second-half rho (stability) and the share of
    blocks with |z| > 1.96 (should be ~5% under a random walk).

This measures whether trend character is persistent. It does NOT show a
tradeable edge; that is a Test 2 question.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\trend_character_v3.py
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

ANALYTICS_DB = r"C:\Users\opc\gold_ea\data\analytics.duckdb"
TFS = {
    "h1":  {"table": "bars_h1",  "bar_min": 60, "q": 4, "block_bars": 230},   # ~10 trading days
    "m30": {"table": "bars_m30", "bar_min": 30, "q": 8, "block_bars": 460},
}
N_BOOT = 1000
N_PERM = 300
PAIR_BLOCK = 5
SEED = 5


# ----------------------------------------------------------------------------
def vr_z(r, q):
    """Lo-MacKinlay (1988) heteroskedasticity-robust variance-ratio z* for returns r."""
    r = np.asarray(r, dtype=float)
    n = len(r)
    if n < 4 * q:
        return np.nan
    mu = r.mean()
    d = r - mu
    ss = np.sum(d ** 2)
    if ss == 0:
        return np.nan
    var_a = ss / (n - 1)
    cs = np.concatenate([[0.0], np.cumsum(r)])
    qsum = cs[q:] - cs[:-q] - q * mu                      # overlapping q-period sums, demeaned
    m = q * (n - q + 1) * (1 - q / n)
    var_c = np.sum(qsum ** 2) / m
    vr = var_c / var_a
    d2 = d ** 2
    theta = 0.0
    for k in range(1, q):
        delta = np.sum(d2[k:] * d2[:-k]) / ss ** 2
        theta += (2 * (q - k) / q) ** 2 * delta
    return (vr - 1) / np.sqrt(theta) if theta > 0 else np.nan


def block_zs(r, block_bars, q):
    nb = len(r) // block_bars
    return np.array([vr_z(r[b * block_bars:(b + 1) * block_bars], q) for b in range(nb)])


def spearman(x, y):
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < 10:
        return np.nan
    rx, ry = pd.Series(x[m]).rank().values, pd.Series(y[m]).rank().values
    return float(np.corrcoef(rx, ry)[0, 1])


def rho_consecutive(z):
    return spearman(z[:-1], z[1:])


def rho_boot_ci(z, seed=SEED):
    x, y = z[:-1], z[1:]
    m = ~(np.isnan(x) | np.isnan(y))
    x, y = x[m], y[m]
    n = len(x)
    L = max(1, min(PAIR_BLOCK, n // 5))
    nb = int(np.ceil(n / L))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(N_BOOT, nb))
    idx = ((starts[:, :, None] + np.arange(L)[None, None, :]) % n).reshape(N_BOOT, -1)[:, :n]
    rhos = []
    for row in idx:
        rhos.append(np.corrcoef(pd.Series(x[row]).rank().values, pd.Series(y[row]).rank().values)[0, 1])
    return np.nanpercentile(rhos, [2.5, 97.5])


def permutation_null(r, block_bars, q, seed=SEED):
    """rho of consecutive blocks after shuffling returns WITHIN each block (keeps block volatility)."""
    rng = np.random.default_rng(seed)
    nb = len(r) // block_bars
    base = r[:nb * block_bars].reshape(nb, block_bars)
    out = []
    for _ in range(N_PERM):
        perm = np.array([rng.permutation(row) for row in base]).ravel()
        out.append(rho_consecutive(block_zs(perm, block_bars, q)))
    return np.array(out)


def analyse(r, cfg, label):
    z = block_zs(r, cfg["block_bars"], cfg["q"])
    rho = rho_consecutive(z)
    lo, hi = rho_boot_ci(z)
    null = permutation_null(r, cfg["block_bars"], cfg["q"])
    p = float(np.mean(np.abs(null) >= abs(rho)))
    half = len(z) // 2
    rho1, rho2 = rho_consecutive(z[:half]), rho_consecutive(z[half:])
    size = float(np.nanmean(np.abs(z) > 1.96))
    print(f"  {label:6s} blocks={len(z):4d}  mean z={np.nanmean(z):+.2f}  share|z|>1.96={size:.1%} (random walk: ~5%)")
    print(f"         rho(consecutive blocks) = {rho:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]   "
          f"permutation-null |rho|>= observed: p={p:.3f}   null sd={np.nanstd(null):.3f}")
    print(f"         first half rho = {rho1:+.3f}   second half rho = {rho2:+.3f}")
    return {"label": label, "n_blocks": len(z), "rho": rho, "ci_lo": lo, "ci_hi": hi, "perm_p": p,
            "rho_first_half": rho1, "rho_second_half": rho2, "share_abs_z_gt_1.96": size}


def load_returns(con, cfg):
    df = con.execute(f"SELECT bar_ts, close FROM {cfg['table']} WHERE close IS NOT NULL ORDER BY bar_ts").fetchdf()
    ts = pd.to_datetime(df["bar_ts"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    r = np.diff(np.log(df["close"].values.astype(float)))
    gap_min = (ts.values[1:] - ts.values[:-1]).astype("timedelta64[m]").astype(int)
    return r[gap_min <= 3 * cfg["bar_min"]]           # drop returns spanning weekends/holidays/long gaps


def main(con=None):
    if con is None:
        con = duckdb.connect(ANALYTICS_DB, read_only=True)
    rows = []
    print("Trend-character persistence (variance-ratio z, consecutive NON-overlapping blocks)")
    for tf, cfg in TFS.items():
        r = load_returns(con, cfg)
        print(f"\n{tf.upper()}: {len(r):,} usable returns, block={cfg['block_bars']} bars, VR horizon q={cfg['q']} bars")
        rows.append({"timeframe": tf, **analyse(r, cfg, tf)})
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trend_character_v3_results.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nSaved: {out}")
    print("Read: rho CI excluding 0 AND small permutation p = trend character genuinely persists across blocks; "
          "CI including 0 = no evidence. Positive rho does not imply a tradeable edge.")


if __name__ == "__main__":
    main()