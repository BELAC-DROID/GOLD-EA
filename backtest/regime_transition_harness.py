"""
Shared regime-transition test harness (v2, 2026-09-21).

Takes a dataframe already labeled with a "regime" and "prior_regime"
column, and scores a transition model (P(regime | prior_regime), learned on
the training fold) against the naive majority-class baseline under Brier
scoring, over the pre-committed walk-forward window matrix. A hard-guess
persistence baseline is NOT used (unfair under Brier scoring - see Metric C).

WHAT CHANGED vs v1 (fully backward compatible: run_combo, class_freqs,
brier and run_all_combos keep their names, arguments and return values, and
the Brier numbers are identical):
  * Every combo now also reports the EFFECT SIZE - % Brier improvement over
    majority - and a circular block-bootstrap 95% CI on the paired
    per-observation Brier difference (model minus majority).
  * Verdict codes replace raw "beats majority" counts, because a raw win can
    be a rounding-error margin (Metric I: 0.1-0.4% gains were reported as
    "robust" wins, and with n~80k even a 0.2% gain is "significant"):
        '+'  CI excludes 0 AND gain >= MIN_MATERIAL_GAIN_PCT   (real & material)
        't'  CI excludes 0 but gain <  MIN_MATERIAL_GAIN_PCT   (significant but trivial)
        '0'  CI includes 0                                     (no detectable effect)
        '-'  model significantly WORSE than majority
        '.'  no valid folds
    MIN_MATERIAL_GAIN_PCT = 1.0 is a JUDGEMENT CALL (from Metric I: ~0.1-0.4%
    was practically nothing, ~4-6% was clearly meaningful). Change it if you
    disagree; results are also printed as raw % so nothing is hidden.
  * The old return value of run_all_combos (wins, total) is unchanged (wins =
    raw point-estimate wins) so existing scripts (Hurst, weekend gap) keep
    working. Use run_all_combos_detailed() for the structured results.

BLOCK LENGTH: block_len (in observations) must cover the serial dependence in
your labels. Default 20. If your labels come from overlapping windows (e.g. the
60-day Hurst window), pass block_len=60 or more; too-short blocks make the CI
too narrow and produce false "significant" results. The block is capped at
n/5 so the bootstrap always has >= 5 blocks.
"""

import numpy as np
from walk_forward_matrix import COMBOS, generate_splits

MIN_MATERIAL_GAIN_PCT = 1.0
N_BOOT = 1000
RNG_SEED = 11


# ---------------- unchanged v1 helpers (kept for compatibility) ----------------
def class_freqs(labels, regimes):
    if len(labels) == 0:
        return {r: 1 / len(regimes) for r in regimes}
    counts = {r: 0 for r in regimes}
    for l in labels:
        counts[l] += 1
    n = len(labels)
    return {r: counts[r] / n for r in regimes}


def brier(pred, actual, regimes):
    return sum((pred[r] - (1.0 if r == actual else 0.0)) ** 2 for r in regimes)


def run_combo(df, combo, regimes, date_col="day"):
    """v1 behaviour: returns (model_brier, majority_brier, n) or None."""
    res = score_combo(df, combo, regimes, date_col)
    if res is None:
        return None
    return round(res["brier_model"], 4), round(res["brier_major"], 4), res["n_test"]


# ---------------- v2 scoring ----------------
def block_boot_ci(d, block_len, n_boot=N_BOOT, seed=RNG_SEED):
    """Circular block bootstrap CI for mean(d); d must be in time order."""
    d = np.asarray(d, dtype=float)
    n = len(d)
    L = max(1, min(int(block_len), n // 5 if n >= 5 else 1))
    ext = np.concatenate([d, d[:L]])
    cs = np.concatenate([[0.0], np.cumsum(ext)])
    bs = cs[L:L + n] - cs[:n]
    nb = int(np.ceil(n / L))
    starts = np.random.default_rng(seed).integers(0, n, size=(n_boot, nb))
    means = bs[starts].sum(axis=1) / (nb * L)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return d.mean(), lo, hi


def score_combo(df, combo, regimes, date_col="day", block_len=20):
    idx = {r: i for i, r in enumerate(regimes)}
    k = len(regimes)
    cur_all = df["regime"].map(idx).values
    pri_all = df["prior_regime"].map(idx).values
    model_parts, major_parts = [], []
    for s in generate_splits(combo):
        tr = ((df[date_col] >= s["train_start"]) & (df[date_col] <= s["train_end"])).values
        te = ((df[date_col] >= s["test_start"]) & (df[date_col] <= s["test_end"])).values
        if tr.sum() < 30 or te.sum() < 10:
            continue
        c_tr, p_tr = cur_all[tr].astype(int), pri_all[tr].astype(int)
        T = np.zeros((k, k))
        np.add.at(T, (p_tr, c_tr), 1)
        rows = T.sum(axis=1, keepdims=True)
        P = np.where(rows > 0, T / np.maximum(rows, 1), 1.0 / k)   # empty row -> uniform (as v1)
        maj = np.bincount(c_tr, minlength=k) / len(c_tr)
        c_te, p_te = cur_all[te].astype(int), pri_all[te].astype(int)
        onehot = np.eye(k)[c_te]
        model_parts.append(((P[p_te] - onehot) ** 2).sum(axis=1))
        major_parts.append(((maj[None, :] - onehot) ** 2).sum(axis=1))
    if not model_parts:
        return None
    m, j = np.concatenate(model_parts), np.concatenate(major_parts)
    diff, lo, hi = block_boot_ci(m - j, block_len)
    maj_mean = j.mean()
    gain = -diff / maj_mean * 100
    gain_lo, gain_hi = -hi / maj_mean * 100, -lo / maj_mean * 100
    if hi < 0:
        code = "+" if gain >= MIN_MATERIAL_GAIN_PCT else "t"
    elif lo > 0:
        code = "-"
    else:
        code = "0"
    return {"n_test": len(m), "brier_model": float(m.mean()), "brier_major": float(maj_mean),
            "gain_pct": float(gain), "gain_ci_lo": float(gain_lo), "gain_ci_hi": float(gain_hi), "code": code}


def run_all_combos_detailed(df, regimes, label, date_col="day", block_len=20, verbose=True):
    if verbose:
        print(f"  regime distribution: {class_freqs(df['regime'].tolist(), regimes)}")
    results = []
    for combo in COMBOS:
        r = score_combo(df, combo, regimes, date_col, block_len)
        if r is None:
            if verbose:
                print(f"    {combo['name']:25s}  no valid folds")
            continue
        r = {"combo": combo["name"], **r}
        results.append(r)
        if verbose:
            print(f"    {combo['name']:25s}  n_test={r['n_test']:6d}  model={r['brier_model']:.4f}  "
                  f"majority={r['brier_major']:.4f}  gain={r['gain_pct']:+.2f}% "
                  f"[{r['gain_ci_lo']:+.2f},{r['gain_ci_hi']:+.2f}]  -> {r['code']}")
    if verbose and results:
        codes = "".join(r["code"] for r in results)
        print(f"  Summary ({label}): codes[{codes}]  '+' material&sig, 't' sig but <{MIN_MATERIAL_GAIN_PCT:g}% (trivial), "
              f"'0' none, '-' worse | mean gain {np.mean([r['gain_pct'] for r in results]):+.2f}%")
        print("  (combos overlap heavily: window-robustness, not independent replication)")
    return results


def run_all_combos(df, regimes, label, date_col="day", block_len=20):
    """v1-compatible: prints (now with effect sizes) and returns (raw_point_wins, total)."""
    results = run_all_combos_detailed(df, regimes, label, date_col, block_len, verbose=True)
    wins = sum(1 for r in results if r["brier_model"] < r["brier_major"])
    total = len(results)
    print(f"  Raw point-estimate wins (v1 style, NOT significance): {wins}/{total}")
    return wins, total