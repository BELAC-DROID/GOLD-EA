"""
Metric K follow-up: is the gold/DXY correlation-regime persistence just a
volatility effect?

Metric K found that the gold/DXY correlation of 10-day blocks (hourly returns)
varies far more than sampling noise and persists strongly from block to block
(Spearman +0.65). One way that could be misleading: if the correlation is
simply higher in high-volatility blocks (macro-news periods move both markets
together) and volatility regimes persist, then "correlation regimes" would be
volatility regimes in disguise.

This script:
  1. Computes for each block: rho_b (gold/DXY return correlation), gold
     volatility, DXY volatility (std of hourly returns).
  2. Reports how strongly rho_b relates to each volatility (Spearman).
  3. Removes the part of rank(rho_b) explained by volatility (OLS on ranks) and
     tests persistence of the RESIDUAL between consecutive blocks (bootstrap CI
     + permutation p), as in Metric K - three ways: controlling for gold
     volatility only, DXY volatility only, and both.

HOW TO READ IT (lesson from validating this script on synthetic data):
  DXY volatility is partly an OUTCOME of the coupling - when the two markets
  are tightly coupled, DXY carries gold's shocks and its volatility rises - so
  controlling for DXY volatility can erase a genuine correlation regime
  (over-control). Controlling for GOLD volatility only is the cleaner test of
  "is this just gold's own volatility regime?".
    * persistence survives the gold-vol control  -> not merely a gold-volatility
      regime (evidence for genuine correlation regimes, though not proof)
    * persistence vanishes with gold vol removed -> it is largely a volatility regime
    * vanishes only when DXY vol is also removed  -> ambiguous (could be either);
      do not over-interpret.

Run:  python C:\\Users\\opc\\gold_ea\\backtest\\dxy_k_vol_control.py
"""

import os
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxy_alignment_check as A
import dxy_metrics_kl as M

BLOCK_H = M.BLOCK_H
N_PERM = 2000
SEED = 29


def block_table(gold_g, dxy_g):
    gh, dh = gold_g.resample("1h").last(), dxy_g.resample("1h").last()
    both = pd.concat([np.log(gh).diff(), np.log(dh).diff()], axis=1, keys=["g", "d"]).dropna()
    both = both[both.index.dayofweek < 5]
    rg, rd = both["g"].values, both["d"].values
    nb = len(both) // BLOCK_H
    rows = []
    for b in range(nb):
        s = slice(b * BLOCK_H, (b + 1) * BLOCK_H)
        rows.append({"start": both.index[b * BLOCK_H], "rho": np.corrcoef(rg[s], rd[s])[0, 1],
                     "vol_g": rg[s].std(ddof=1), "vol_d": rd[s].std(ddof=1)})
    return pd.DataFrame(rows)


def persistence(x, label):
    r1 = M.spearman_lag1(x)
    n = len(x) - 1
    L = max(1, min(M.PAIR_BLOCK, n // 5))
    rng = np.random.default_rng(SEED)
    nb = int(np.ceil(n / L))
    starts = rng.integers(0, n, size=(1000, nb))
    idx = ((starts[:, :, None] + np.arange(L)[None, None, :]) % n).reshape(1000, -1)[:, :n]
    ra, rb = pd.Series(x[:-1]).rank().values, pd.Series(x[1:]).rank().values
    lo, hi = np.nanpercentile([np.corrcoef(ra[i], rb[i])[0, 1] for i in idx], [2.5, 97.5])
    p = float(np.mean(np.abs([M.spearman_lag1(rng.permutation(x)) for _ in range(N_PERM)]) >= abs(r1)))
    print(f"  {label:38s} lag-1 Spearman = {r1:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]  permutation p = {p:.3f}")
    return r1, lo, hi, p


def analyse(bt):
    rho = bt["rho"].values
    rk = lambda v: pd.Series(v).rank().values
    print(f"blocks: {len(bt)}")
    for col, nm in [("vol_g", "gold volatility"), ("vol_d", "DXY volatility")]:
        c = np.corrcoef(rk(rho), rk(bt[col].values))[0, 1]
        print(f"  Spearman(rho_b, {nm}) = {c:+.3f}")
    y = rk(rho)
    controls = {"gold vol only": ["vol_g"], "DXY vol only": ["vol_d"], "both volatilities": ["vol_g", "vol_d"]}
    print("\npersistence between consecutive blocks:")
    out = {"raw": persistence(rho, "raw rho_b (as in Metric K)")}
    for name, cols in controls.items():
        X = np.column_stack([np.ones(len(bt))] + [rk(bt[c].values) for c in cols])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        r2 = 1 - resid.var() / y.var()
        out[name] = persistence(resid, f"rho_b minus {name} (R2={r2:.2f})")
    print("\nvolatility persistence itself (for reference):")
    persistence(bt["vol_g"].values, "gold volatility")
    persistence(bt["vol_d"].values, "DXY volatility")
    return out


def main(con=None):
    if con is None:
        con = duckdb.connect(A.ANALYTICS_DB, read_only=True)
    ts = A.discover_ts_col(con, A.DXY_TABLE)
    gold = A.load_minute_close(con, A.GOLD_TABLE, "minute_ts")
    dxy = A.load_minute_close(con, A.DXY_TABLE, ts)
    start, end = max(gold.index.min(), dxy.index.min()), min(gold.index.max(), dxy.index.max())
    bt = block_table(A.on_grid(gold, start, end), A.on_grid(dxy, start, end))
    res = analyse(bt)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxy_k_vol_control_blocks.csv")
    bt.to_csv(out, index=False)
    print(f"\nSaved block table: {out}")
    return res


if __name__ == "__main__":
    main()