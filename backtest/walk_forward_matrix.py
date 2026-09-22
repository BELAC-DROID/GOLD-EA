"""
Shared, pre-committed walk-forward window matrix. Applied identically
to every calibration metric that uses walk-forward testing, so window
choice can't be selected after seeing which one performs best (that
would reintroduce look-ahead bias into the validation design itself).

Generates multiple sequential folds per combo (stepping forward through
the full dataset), not just anchor points - results are pooled/averaged
per combo, matching standard walk-forward practice.
"""

import pandas as pd

DATA_START = "2019-01-01"
DATA_END = "2026-09-18"

COMBOS = [
    {"name": "expanding_test1yr", "scheme": "expanding", "test_months": 12},
    {"name": "expanding_test6mo", "scheme": "expanding", "test_months": 6},
    {"name": "rolling_2yr_test1yr", "scheme": "rolling", "train_years": 2, "test_months": 12},
    {"name": "rolling_3yr_test1yr", "scheme": "rolling", "train_years": 3, "test_months": 12},
    {"name": "rolling_4yr_test1yr", "scheme": "rolling", "train_years": 4, "test_months": 12},
    {"name": "rolling_3yr_test6mo", "scheme": "rolling", "train_years": 3, "test_months": 6},
]


def generate_splits(combo, data_start=DATA_START, data_end=DATA_END, min_train_years=2):
    data_start = pd.Timestamp(data_start)
    data_end = pd.Timestamp(data_end)
    test_months = combo["test_months"]

    if combo["scheme"] == "rolling":
        train_len = pd.DateOffset(years=combo["train_years"])
        cur_test_start = data_start + train_len
    else:
        cur_test_start = data_start + pd.DateOffset(years=min_train_years)

    splits = []
    while cur_test_start <= data_end:
        test_end = min(cur_test_start + pd.DateOffset(months=test_months) - pd.DateOffset(days=1), data_end)
        train_end = cur_test_start - pd.DateOffset(days=1)
        train_start = (cur_test_start - train_len) if combo["scheme"] == "rolling" else data_start
        splits.append({
            "train_start": train_start.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": cur_test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
        })
        cur_test_start += pd.DateOffset(months=test_months)
    return splits