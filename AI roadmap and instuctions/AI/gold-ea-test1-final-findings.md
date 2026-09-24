# Gold EA — Test 1 Final Findings (Reference)

*Purpose: a lookup reference, not a narrative. Every conclusion below is final as of 2026-09-24, including the 2026 holdout. For the story of how each was reached (bugs found, fixes, re-tests), see gold-ea-progress.md. This file does not replace gold-ea-roadmap.md — that file's current content was not available when this was written and may still list items as outstanding that are closed below; reconcile the two manually or send me the roadmap to merge.*

---

## 1. Data inventory

| Source | Coverage | Use for |
|---|---|---|
| `minute_bars_ohlc` (analytics.duckdb) | 2019-01-01 → 2025-12-31, Dukascopy | All price-structure metrics (A, C, D, E, F, G, H, I) |
| `ticks` source=`dukascopy` (gold_data.db) | 2019-2025 | Interbank reference spread (not used for spread modeling) |
| `ticks` source=`exness` (gold_data.db) | 2026-09-03 → 09-18 | Original one-off spread calibration pull |
| `ticks` source=`exness_live` (gold_data.db) | 2026-01-01 → present, ~71M ticks | Real spread modeling (Metric J); confirmed to match demo-account spread on the one NFP window tested |
| `dxy_m1_ohlc` / `dxy_d1_ohlc` (analytics.duckdb) | 2021-07-19+ / 2019+ | DXY metrics (K, L); verified real, non-placeholder; confirmed timestamp-aligned with gold feed (lag 0, all seasons) |
| `analytics_2026_holdout.duckdb` | 2026-01-01 → 09-18, built from `exness_live` | The 2026 holdout only — **mid-price assumption for OHLC construction is UNCONFIRMED against whatever convention the original Dukascopy pipeline used.** Fine for regime/persistence-style tests; verify before trusting an exact magnitude comparison against 2019-2025. |

**Market context spanning the dataset:** gold traded $1,300–2,600 (2019–2024), $3,000–3,700+ (2025), crossed $4,000 (Oct 2025), hit an all-time high near **$5,590 on Jan 28, 2026** (first inflation-adjusted record, beating 1980), then traded $4,500–5,190 with "$100–200 single-session swings" reported as routine. Drivers: record central-bank buying, weak dollar, geopolitical tension. The 2023 H2 period also saw a sharp, real volatility regime shift tied to the Israel-Gaza conflict's onset. **Any fixed-dollar assumption breaks across this history — this has now caused bugs four separate times (level spacing, range prediction, the level-reaction walk-forward test itself, and a raw-dollar MAE comparison in the 2026 holdout analysis). Always work in %-of-price terms.**

---

## 2. Metric-by-metric verdicts

### A — Range prediction
- **Use:** an adaptive trailing 5–20 session mean range, as % of prior close. NOT a long-window training-mean model.
- **Do not use** the training-mean model for Asian at all — it loses to the trailing baseline.
- **2026 holdout:** the trailing-average model's edge over the old approach holds (confirmed on genuinely new data). **But fixed 2019–2025 interval calibration badly fails in 2026** — Asian 80%/90% intervals covered only 39%/62% of actual outcomes (target 80%/90%); London/NY also undercovered, less severely. **Any interval width or threshold calibrated on a historical window must be treated as provisional and revisited/made adaptive — this is now a demonstrated failure mode.**
- **Sessions:** DST-aware London/NY definitions matter, especially for NY (fixed-UTC 13:00 start misses summer 08:30 ET releases about half the year).

### B — Level-reaction
- **No predictive value.** Both tiered and pooled models sit at the class-frequency (entropy) floor.
- **Keep tiering** for touch-*detection* correctness (it fixed a real measurement bug) — **don't use it for prediction confidence.**

### C — Session volatility-regime persistence
- **Confirmed, Asian only, moderate:** significant at lookback ≥100 sessions, not at 60. **2026 holdout: holds and strengthens** (lookback 150 gave +8.1%, stronger than in-sample).
- **London, NY:** no effect in the original 2019–2025 study.
- **New candidate (2026 holdout only):** London showed a significant short-lookback (60) effect, replicated across both session definitions — **flagged as a hypothesis to watch, not an established effect.** One year of data found something 5+ years didn't; don't design around it yet.

### D — Trend/mean-reversion character (Hurst)
- **No evidence of persistence.** The original R/S-based method's "modest real persistence" finding was a measurement artifact — reproducible on pure noise at the same magnitude as the real result. The variance-ratio replacement (non-overlapping blocks, unbiased-centred statistic) also found nothing (rho ≈ −0.02, CI −0.16 to +0.13).
- **Do not build trend/mean-reversion regime confidence into Phase 4/5 on this basis.**

### E — Distribution shape stability
- **Not "generally unstable."** Most of the calendar shows no detectable shift in skew/kurtosis between adjacent periods.
- **Can detect genuine regime shocks:** the only unambiguous finding (p=0.000, robust across both a range-ratio and a genuine signed-return formulation) was Asian session, H2 2023 — tied to the real Israel-Gaza-driven gold rally.
- **Design implication:** build a shock/regime-detection capability that can flag "possibly in a structurally different distribution right now," rather than assuming setups trained on calmer periods generalize through events like this.
- Kurtosis-based findings need much larger samples than skew-based ones to trust — always check which one is driving a claimed result.

### F — Weekend gap
- **No persistence.** Confirmed null with proper significance testing (model significantly *worse* than majority in 5/6 combos — an estimation-cost artifact, not anti-persistence).

### G — Session-open (opening-range) prediction
- **Positive claim withdrawn.** Same flaw as A's original version: the "beats naive" result came from a weak lag-1 baseline. A trailing 5–20 session average beats the training-mean model here too, in nearly every session/window combo.
- **Use the same adaptive trailing approach as Metric A** for opening-range expectations.

### H — Anomaly-flagging precision
- **Confirmed, robust — strongest holdout result in the whole set.** 2026 holdout: 7 of 10 opening-range-flag tests significant, every lift *exceeding* its in-sample value (Asian 3.8x, London/NY 2.1–2.7x).
- **Calendar flag:** same direction (lift >1x) everywhere on the holdout, but underpowered at one year's worth of events — read as a sample-size issue, not a disappearing effect.
- **Use as a risk/state indicator, not a predictor** — even on flagged days, most sessions are still not high-volatility.
- Use the DST-aware NY session mapping — the fixed-UTC NY window misses summer 08:30 ET releases.

### I — Cross-timeframe intraday regime persistence
- **Confirmed and strengthened on the 2026 holdout, across every timeframe** (D1 +2.6%, H4 +5.9%, H1 +7.6%, M30 +8.9%, all with CIs excluding zero — D1 newly established, it was never confidently significant in-sample).
- **Use time-of-day-relative regime labels** (rank against the same time-of-day slot's history), **not raw percentile-of-range** — the raw version is dominated by which hour it is, not real volatility state.
- **Use short lags** (previous bar / previous session) — persistence at a ~33-day lag is negligible everywhere.
- **The old "build confidence at D1/H4 only" restriction is withdrawn.** Intraday (H4/H1/M30) regime confidence is supported.

### J — Catalyst magnitude / spread model
- **Confirmed via direct spread validation** against real Exness ticks (not just price-magnitude proxy).
- **`SPIKE_TEMPLATE`** (in `spread_model.py`) rebuilt from 8 real NFP events — the original single-event calibration was an outlier (peak 1.96x vs. the real 8-event mean of 1.577x, CI 1.30–1.90).
- **`FAMILY_SCALE_FACTOR`:** NFP 1.00 (reference), CPI 0.91, FOMC 0.74, **GDP and PCE merged into one family "GDP_PCE" (0.28)** — they co-release at the same timestamp ~89% of the time (BEA's actual schedule), so keeping them separate was measuring a blended effect under two different names.
- **The worst-case (max) column is still small-sample (n=8)** — revisit periodically as more NFP events accumulate in `exness_live`. Not urgent.

### K — DXY correlation-regime persistence
- **Confirmed on the original 2021–2025 data:** 10-day gold/DXY correlation regimes are real (94% of block-to-block variance exceeds sampling noise) and persist strongly (+0.648, CI +0.47 to +0.77) — survives a volatility-control check (persistence remains at +0.606 after removing gold's own volatility as an explanation).
- **2026 holdout: inconclusive, not a contradiction.** Only 17 blocks available in 8.5 months; the bootstrap CI and permutation p-value disagree at that sample size. **The original multi-year finding stands on its own evidence** — revisit once more 2026+ data accumulates.
- Correlation was weakest in 2025 (−0.31 vs. −0.41 to −0.60 in other years) — worth monitoring, not yet a trend.

### L — DXY lead-lag
- **Confirmed, cleanly, and remarkably stable.** The relationship is contemporaneous only — no exploitable lead-lag at minute scale, in either the original data or the 2026 holdout.
- **2026 holdout essentially reproduced the original numbers** (rho(0) −0.399 vs. −0.379 overall; −0.691 vs. −0.658 in the NY release window) despite a totally different price level and volatility regime — DXY cannot be used as a leading indicator, but is a strong *simultaneous* read on whether a gold move is dollar-driven, especially around releases.

---

## 3. Design principles for Phase 4/5 (drawn from the pattern across all of the above)

1. **Adaptive beats fixed, every time it was tested head-to-head.** The trailing-window model (A), the rolling time-of-day-relative regime labels (I), and the rolling percentile flags (H) all generalized to the 2026 holdout — several got *stronger*. The one static, historically-fixed calibration (A's interval quantiles) is the one thing that broke. Treat this as a standing rule, not a one-off finding: any threshold, interval, or scale factor calibrated on a fixed historical window should be built to update, not frozen in.
2. **Never use raw dollar/price-level comparisons across time.** Always %-of-price. This has caused real bugs four separate times across this project.
3. **Session windows need DST-awareness**, not fixed UTC — this changes which economic releases fall inside which session, especially for NY.
4. **Always attach a significance test and an effect size to a "beats baseline" claim** — raw win-counts (as several original metric scripts did) inflate positive findings and hide the difference between a real effect and sampling noise, especially for kurtosis-based statistics.
5. **Build a shock/regime-detection capability.** Two real, large distributional shifts were found in this dataset (Oct–Dec 2023, and the entire 2026 window) — Phase 4/5 setups need a way to recognize "this may not be a normal period" rather than assuming stationarity.
6. **Don't overstate a same-timestamp calendar collision's implications** — when two economic releases habitually co-occur (GDP/PCE), a "family" scale factor for one of them is really measuring the blend, not the individual release; check for this before trusting any per-event-type parameter.

---

## 4. What's still open (low urgency, not blocking Phase 4)

- **`spread_model.py`'s worst-case (max) spread multiplier** — built from only 8 NFP events; revisit as more accumulate in `exness_live`.
- **The new London/Metric-C candidate finding** — watch as more 2026+ data comes in; don't design a setup around it yet.
- **The 2026 holdout's mid-price assumption** — confirm against the original Dukascopy bar-construction convention if an exact magnitude comparison (not just a directional one) is ever needed between the two periods.
- **Metric K's weakening 2025 correlation** — monitor, not yet actionable.
