"""
Shared statistical core for Metric E (distribution shape stability), v2.

Original distribution_shape_stability.py reported raw |skew_diff| and
|kurt_diff| between a fold's train and test period with NO significance
test - every other Phase 3 metric got a bootstrap/permutation treatment
after the 2026-09-21 review, this one didn't. That almost certainly
explains the extreme number already on record (Asian kurtosis "0.192 to
52.515 across folds"): kurtosis is a high-variance statistic at small n
(the old script's floor was just len() >= 30), so one unusually volatile
day in a 30-observation window can dominate it. Without a null to compare
against, there was no way to tell a real distributional shift from that.

BLOCK-PERMUTATION NULL: pool train+test (in original time order), split
into contiguous blocks of length BLOCK_LEN, shuffle the BLOCK ORDER (not
individual observations - preserves local runs of high/low volatility
days, i.e. does not destroy volatility clustering the way a naive
observation-level shuffle would), take the first n_train (pseudo)pooled
observations as a fake "train" and the rest as a fake "test", and recompute
the skew/kurt diff. Repeating this many times answers: "if the train/test
boundary had fallen at a different, arbitrary point in this same block of
data, how big a skew/kurt diff would that alone produce?" The p-value is
the share of null draws at least as extreme as what was actually observed.
"""

import numpy as np
from scipy import stats

BLOCK_LEN = 5
N_PERM = 1000
SEED = 41
MIN_N = 30            # unchanged from v1 - the floor below which skew is unreliable
MIN_N_KURTOSIS = 60   # kurtosis needs more data than skew to be trustworthy; flagged, not dropped


def block_permutation_pvalue(train, test, block_len=BLOCK_LEN, n_perm=N_PERM, seed=SEED):
    """Returns (obs_skew_diff, p_skew, obs_kurt_diff, p_kurt)."""
    train, test = np.asarray(train, dtype=float), np.asarray(test, dtype=float)
    n1, n2 = len(train), len(test)
    pooled = np.concatenate([train, test])
    n = len(pooled)

    obs_skew_diff = abs(stats.skew(train) - stats.skew(test))
    obs_kurt_diff = abs(stats.kurtosis(train) - stats.kurtosis(test))

    L = max(1, min(block_len, n // 4 if n >= 4 else 1))
    nb = int(np.ceil(n / L))
    padded = np.concatenate([pooled, pooled[:L]])  # circular padding so every block is full length
    blocks = [padded[b * L:(b + 1) * L] for b in range(nb)]

    rng = np.random.default_rng(seed)
    null_skew, null_kurt = np.empty(n_perm), np.empty(n_perm)
    for i in range(n_perm):
        order = rng.permutation(nb)
        shuffled = np.concatenate([blocks[b] for b in order])[:n]
        pt, pe = shuffled[:n1], shuffled[n1:n1 + n2]
        null_skew[i] = abs(stats.skew(pt) - stats.skew(pe))
        null_kurt[i] = abs(stats.kurtosis(pt) - stats.kurtosis(pe))

    p_skew = float(np.mean(null_skew >= obs_skew_diff))
    p_kurt = float(np.mean(null_kurt >= obs_kurt_diff))
    return obs_skew_diff, p_skew, obs_kurt_diff, p_kurt


def fold_summary(train, test, label=""):
    """One fold's full stats dict, or None if either side is too thin to test at all."""
    n1, n2 = len(train), len(test)
    if n1 < MIN_N or n2 < MIN_N:
        return None
    skew_diff, p_skew, kurt_diff, p_kurt = block_permutation_pvalue(train, test)
    low_n_kurt = n1 < MIN_N_KURTOSIS or n2 < MIN_N_KURTOSIS
    return {
        "label": label, "n_train": n1, "n_test": n2,
        "train_skew": float(stats.skew(train)), "test_skew": float(stats.skew(test)),
        "skew_diff": skew_diff, "p_skew": p_skew,
        "train_kurt": float(stats.kurtosis(train)), "test_kurt": float(stats.kurtosis(test)),
        "kurt_diff": kurt_diff, "p_kurt": p_kurt, "low_n_kurtosis_warning": low_n_kurt,
    }