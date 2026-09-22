"""
Phase 3 - Test 1, Metric A: Range Prediction Walk-Forward Calibration

Tests whether each session's train-period mean range still predicts
actual test-period ranges out-of-sample, across three expanding
walk-forward splits. Scores against a naive lag-1 (yesterday's actual
range) baseline, with a bootstrap 95% CI on the mean absolute error.

Reuses the exact minute-bar / session-range construction from
baseline_profiler.py so the two stay consistent.
"""

import duckdb
import numpy as np

DB_PATH = r"C:\Users\opc\gold_ea\data\gold_data.db"

CLOSURE_START_MIN = 20 * 60 + 58
CLOSURE_END_MIN = 22 * 60

SESSIONS = {
    "asian":  (0, 8),
    "london": (8, 16),
    "ny":     (13, 21),
}

SPLITS = [
    ("2019-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("2019-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
    ("2019-01-01", "2024-12-31", "2025-01-01", None),  # None = up to last available day
]

N_BOOTSTRAP = 2000
RNG = np.random.default_rng(42)


def connect():
    con = duckdb.connect()
    con.execute("INSTALL sqlite;")
    con.execute("LOAD sqlite;")
    con.execute(f"ATTACH '{DB_PATH}' AS gold (TYPE sqlite);")
    return con


def build_minute_bars(con):
    con.execute("""
        CREATE OR REPLACE TEMP TABLE minute_bars AS
        SELECT
            date_trunc('minute', to_timestamp(timestamp_utc_ms / 1000.0)) AS minute_ts,
            (extract(hour FROM to_timestamp(timestamp_utc_ms / 1000.0)) * 60
             + extract(minute FROM to_timestamp(timestamp_utc_ms / 1000.0))) AS minute_of_day,
            min((bid + ask) / 2.0) AS low,
            max((bid + ask) / 2.0) AS high
        FROM gold.ticks
        WHERE source = 'dukascopy'
        GROUP BY 1, 2
    """)


def daily_session_ranges(con, start_h, end_h):
    """One row per day: (day, day_range), for this session's window."""
    start_min, end_min = start_h * 60, end_h * 60
    rows = con.execute(f"""
        WITH session_bars AS (
            SELECT date_trunc('day', minute_ts) AS day, high, low
            FROM minute_bars
            WHERE minute_of_day >= {start_min} AND minute_of_day < {end_min}
              AND NOT (minute_of_day >= {CLOSURE_START_MIN} AND minute_of_day < {CLOSURE_END_MIN})
        )
        SELECT day, (max(high) - min(low)) AS day_range
        FROM session_bars
        GROUP BY day
        HAVING count(*) > 30
        ORDER BY day
    """).fetchall()
    return rows  # list of (day, range)


def bootstrap_mae_ci(errors, n=N_BOOTSTRAP):
    errors = np.array(errors)
    boot_means = [
        np.mean(RNG.choice(errors, size=len(errors), replace=True))
        for _ in range(n)
    ]
    lo, hi = np.percentile(boot_means, [2.5, 97.5])
    return lo, hi


def run_split(con, session_name, start_h, end_h, train_start, train_end, test_start, test_end):
    all_days = daily_session_ranges(con, start_h, end_h)

    train = [(d, r) for d, r in all_days if str(d.date()) >= train_start and str(d.date()) <= train_end]
    if test_end is None:
        test = [(d, r) for d, r in all_days if str(d.date()) >= test_start]
    else:
        test = [(d, r) for d, r in all_days if str(d.date()) >= test_start and str(d.date()) <= test_end]

    if not train or len(test) < 2:
        return None

    train_mean = np.mean([r for _, r in train])

    # naive baseline: yesterday's actual range predicts today's range
    test_sorted = sorted(test, key=lambda x: x[0])
    model_errors, naive_errors = [], []
    for i in range(1, len(test_sorted)):
        actual = test_sorted[i][1]
        naive_pred = test_sorted[i - 1][1]
        model_errors.append(abs(actual - train_mean))
        naive_errors.append(abs(actual - naive_pred))

    model_mae = np.mean(model_errors)
    naive_mae = np.mean(naive_errors)
    model_rmse = np.sqrt(np.mean(np.square(model_errors)))
    naive_rmse = np.sqrt(np.mean(np.square(naive_errors)))
    model_ci = bootstrap_mae_ci(model_errors)
    naive_ci = bootstrap_mae_ci(naive_errors)

    return {
        "session": session_name,
        "train_days": len(train),
        "test_days": len(test_sorted) - 1,
        "train_mean_range": round(train_mean, 3),
        "model_mae": round(model_mae, 3),
        "model_mae_95ci": (round(model_ci[0], 3), round(model_ci[1], 3)),
        "model_rmse": round(model_rmse, 3),
        "naive_mae": round(naive_mae, 3),
        "naive_mae_95ci": (round(naive_ci[0], 3), round(naive_ci[1], 3)),
        "naive_rmse": round(naive_rmse, 3),
        "beats_naive": model_mae < naive_mae,
    }


if __name__ == "__main__":
    con = connect()
    print("Building minute bars (scans all 282M rows - expect a few minutes)...")
    build_minute_bars(con)
    print("Done.\n")

    for split_i, (train_start, train_end, test_start, test_end) in enumerate(SPLITS, 1):
        test_label = test_end if test_end else "latest available"
        print(f"=== Split {split_i}: train {train_start}->{train_end}, test {test_start}->{test_label} ===")
        for name, (start_h, end_h) in SESSIONS.items():
            result = run_split(con, name, start_h, end_h, train_start, train_end, test_start, test_end)
            if result is None:
                print(f"  {name:8s}  insufficient data for this split")
                continue
            flag = "BEATS naive" if result["beats_naive"] else "worse than naive"
            print(
                f"  {name:8s}  model MAE={result['model_mae']:6.3f} "
                f"(95% CI {result['model_mae_95ci']})  vs  "
                f"naive MAE={result['naive_mae']:6.3f} "
                f"(95% CI {result['naive_mae_95ci']})  -> {flag}"
            )
        print()