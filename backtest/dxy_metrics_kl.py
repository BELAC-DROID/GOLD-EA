"""
Metrics K and L (DXY): correlation-regime persistence and lead-lag.
Run only after dxy_alignment_check.py shows the two feeds are aligned
(it did: peak at lag 0 in all/winter/summer, and both feeds peak at the same
minutes around the 08:30 New York releases).

Design follows the review guidance:
  * RETURNS, never price levels (levels overstate the relationship).
  * No thresholds imported from blogs; everything is measured on this data.
  * Every claim carries a confidence interval or a permutation null.

METRIC L - lead-lag (minute scale)
  corr( gold 1-min return at t , DXY 1-min return at t+k ),  k = -10..+10 min
  * rho(+k) strongly negative for k>0  -> gold's move at t predicts DXY's move
                                            at t+k (gold LEADS)
  * rho(-k) strongly negative for k>0  -> DXY LEADS gold
  * symmetric profile -> no lead-lag beyond the contemporaneous relationship.
  Reported for all minutes, for the 08:25-08:45 New York window (weekday data
  releases: NFP, CPI, claims, ...) and for everything outside it. 95% CIs by
  bootstrapping whole days. Also reports the asymmetry rho(+k) - rho(-k)
  with its CI. A lead of a minute or two would not be tradeable at retail
  latency with Exness spreads; this only measures it.

METRIC K - correlation-regime persistence
  * Hourly returns of both series; consecutive NON-overlapping blocks of
    BLOCK_H return pairs (~10 trading days); rho_b = gold/DXY return
    correlation in block b.
  * Signal-to-noise: how much of the variation of rho_b across blocks exceeds
    what sampling noise alone would produce? If none, "correlation regimes" do
    not exist in this data.
  * Persistence: Spearman rank correlation of rho_b with rho_(b+1), with a
    block-bootstrap CI and a permutation p-value (shuffling block order).
  * Per-year correlation for context.

Coverage note: gold minute bars end where the analytics table ends (printed
below); DXY data beyond that is unused.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\dxy_metrics_kl.py
Output: console + dxy_metrics_kl_results.csv
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxy_alignment_check as A

ANALYTICS_DB = A.ANALYTICS_DB
LEAD_LAGS = list(range(-10, 11))
N_BOOT_DAYS = 500
BLOCK_H = 230
N_PERM = 2000
PAIR_BLOCK = 3
SEED = 17


# ----------------------------------------------------------------------------
# Metric L
# ----------------------------------------------------------------------------
def _rho(stats):
    """stats (..., 6): n, sx, sy, sxx, syy, sxy -> pearson rho."""
    n, sx, sy, sxx, syy, sxy = [stats[..., i] for i in range(6)]
    den = np.sqrt((n * sxx - sx ** 2) * (n * syy - sy ** 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        return (n * sxy - sx * sy) / den


def lead_lag(gold_g, dxy_g):
    g = np.log(gold_g).diff().values
    d = np.log(dxy_g).diff()
    idx = gold_g.index
    day_codes, _ = pd.factorize(idx.normalize())
    ndays = day_codes.max() + 1
    ny = idx.tz_localize("UTC").tz_convert("America/New_York")
    mny = ny.hour * 60 + ny.minute
    is_rel = np.asarray((mny >= 8 * 60 + 25) & (mny < 8 * 60 + 45) & (ny.dayofweek < 5))
    subsets = {"all minutes": np.ones(len(idx), bool),
               "release window 08:25-08:45 NY": is_rel,
               "outside release window": ~is_rel}
    rng = np.random.default_rng(SEED)
    out = {}
    for sname, smask in subsets.items():
        per_lag = []
        for k in LEAD_LAGS:
            dv = d.shift(-k).values
            valid = smask & ~np.isnan(g) & ~np.isnan(dv)
            x, y, dc = g[valid], dv[valid], day_codes[valid]
            stats = np.stack([np.bincount(dc, weights=w, minlength=ndays)
                              for w in (np.ones_like(x), x, y, x * x, y * y, x * y)], axis=1)   # (ndays, 6)
            per_lag.append(stats)
        per_lag = np.stack(per_lag)                                   # (nlags, ndays, 6)
        point = _rho(per_lag.sum(axis=1))                             # (nlags,)
        boots = np.empty((N_BOOT_DAYS, len(LEAD_LAGS)))
        for b in range(N_BOOT_DAYS):
            di = rng.integers(0, ndays, ndays)
            boots[b] = _rho(per_lag[:, di, :].sum(axis=1))
        out[sname] = (point, boots)
    return out


def report_lead_lag(res):
    rows = []
    ks = np.array(LEAD_LAGS)
    for sname, (point, boots) in res.items():
        lo, hi = np.nanpercentile(boots, [2.5, 97.5], axis=0)
        print(f"\n{sname}")
        print("   lag k(min):   " + " ".join(f"{k:+5d}" for k in [-10, -5, -3, -2, -1, 0, 1, 2, 3, 5, 10]))
        sel = [list(ks).index(k) for k in [-10, -5, -3, -2, -1, 0, 1, 2, 3, 5, 10]]
        print("   rho:          " + " ".join(f"{point[i]:+.3f}" for i in sel))
        print("   CI half-width:" + " ".join(f"{(hi[i] - lo[i]) / 2:.3f}" for i in sel))
        for k in [1, 2, 3]:
            ip, im = list(ks).index(k), list(ks).index(-k)
            diff = point[ip] - point[im]
            bd = boots[:, ip] - boots[:, im]
            dlo, dhi = np.nanpercentile(bd, [2.5, 97.5])
            verdict = "no asymmetry" if dlo <= 0 <= dhi else ("gold LEADS (rho(+k) more negative)" if diff < 0 else "DXY LEADS (rho(-k) more negative)")
            print(f"   asymmetry rho(+{k}) - rho(-{k}) = {diff:+.4f}  95% CI [{dlo:+.4f}, {dhi:+.4f}]  -> {verdict}")
            rows.append({"metric": "L", "subset": sname, "k": k, "asym": diff, "ci_lo": dlo, "ci_hi": dhi, "verdict": verdict})
    return rows


# ----------------------------------------------------------------------------
# Metric K
# ----------------------------------------------------------------------------
def spearman_lag1(x):
    a, b = x[:-1], x[1:]
    return float(np.corrcoef(pd.Series(a).rank().values, pd.Series(b).rank().values)[0, 1])


def correlation_regimes(gold_g, dxy_g):
    gh, dh = gold_g.resample("1h").last(), dxy_g.resample("1h").last()
    both = pd.concat([np.log(gh).diff(), np.log(dh).diff()], axis=1, keys=["g", "d"]).dropna()
    both = both[both.index.dayofweek < 5]
    rg, rd = both["g"].values, both["d"].values
    nb = len(both) // BLOCK_H
    rho = np.array([np.corrcoef(rg[b * BLOCK_H:(b + 1) * BLOCK_H], rd[b * BLOCK_H:(b + 1) * BLOCK_H])[0, 1]
                    for b in range(nb)])
    print(f"hourly return pairs: {len(both):,}   blocks of {BLOCK_H}: {nb}")
    print(f"per-block rho: mean {rho.mean():+.3f}  sd {rho.std(ddof=1):.3f}  "
          f"10th/90th pct {np.percentile(rho, 10):+.3f}/{np.percentile(rho, 90):+.3f}  share > 0: {np.mean(rho > 0):.0%}")

    se2 = np.mean(((1 - rho ** 2) / np.sqrt(BLOCK_H - 1)) ** 2)
    excess = rho.var(ddof=1) - se2
    print(f"sampling-noise sd of a block's rho ~ {np.sqrt(se2):.3f}; between-block sd {rho.std(ddof=1):.3f}; "
          f"variance beyond sampling noise: {max(excess, 0) / rho.var(ddof=1):.0%} of total")

    r1 = spearman_lag1(rho)
    n = len(rho) - 1
    L = max(1, min(PAIR_BLOCK, n // 5))
    rng = np.random.default_rng(SEED)
    nb_ = int(np.ceil(n / L))
    starts = rng.integers(0, n, size=(1000, nb_))
    idx = ((starts[:, :, None] + np.arange(L)[None, None, :]) % n).reshape(1000, -1)[:, :n]
    a, b = rho[:-1], rho[1:]
    ra, rb = pd.Series(a).rank().values, pd.Series(b).rank().values
    boots = np.array([np.corrcoef(ra[i], rb[i])[0, 1] for i in idx])
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    perm = np.array([spearman_lag1(rng.permutation(rho)) for _ in range(N_PERM)])
    p = float(np.mean(np.abs(perm) >= abs(r1)))
    print(f"persistence: Spearman(rho_b, rho_b+1) = {r1:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]  permutation p = {p:.3f}")

    print("per-year hourly-return correlation:")
    yr_rows = []
    for y, g in both.groupby(both.index.year):
        c = g["g"].corr(g["d"])
        print(f"   {y}: rho = {c:+.3f}  (n={len(g):,})")
        yr_rows.append({"metric": "K_year", "year": int(y), "rho": c, "n": len(g)})
    return [{"metric": "K", "n_blocks": nb, "mean_rho": rho.mean(), "sd_rho": rho.std(ddof=1),
             "noise_sd": float(np.sqrt(se2)), "persistence": r1, "ci_lo": lo, "ci_hi": hi, "perm_p": p}] + yr_rows


def main(con=None):
    if con is None:
        con = duckdb.connect(ANALYTICS_DB, read_only=True)
    dxy_ts = A.discover_ts_col(con, A.DXY_TABLE)
    gold = A.load_minute_close(con, A.GOLD_TABLE, "minute_ts")
    dxy = A.load_minute_close(con, A.DXY_TABLE, dxy_ts)
    start, end = max(gold.index.min(), dxy.index.min()), min(gold.index.max(), dxy.index.max())
    print(f"gold {gold.index.min()} -> {gold.index.max()};  DXY {dxy.index.min()} -> {dxy.index.max()}")
    print(f"analysis window (overlap): {start} -> {end}  ({(end - start).days / 365.25:.2f} years)")
    gold_g, dxy_g = A.on_grid(gold, start, end), A.on_grid(dxy, start, end)

    print("\n" + "=" * 80 + "\nMETRIC L - lead-lag (1-minute returns; rho(k) = corr(gold[t], DXY[t+k]))\n" + "=" * 80)
    rows = report_lead_lag(lead_lag(gold_g, dxy_g))
    print("\n" + "=" * 80 + "\nMETRIC K - correlation-regime persistence (hourly returns)\n" + "=" * 80)
    rows += correlation_regimes(gold_g, dxy_g)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxy_metrics_kl_results.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()