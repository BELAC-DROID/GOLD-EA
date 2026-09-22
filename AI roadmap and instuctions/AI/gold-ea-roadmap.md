# XAU/USD Gold EA — Build Roadmap & Progress

*Full consolidation — Phase 3 (Test 1) resolved across all 12 design-doc calibration metrics*

This is the single technical source of truth for the build. See `gold-ea-progress.md` for a shorter summary and `gold-ea-ai-decision-layer.md` (Section 7.5) for the design-level synthesis of findings.

---

## Phase 1: Infrastructure — ✅ Complete
Windows Server 2022 VM, Oracle Cloud UK South. Python↔MT5↔Exness verified, timezone confirmed clean. 6 years of Dukascopy tick data loaded and validated (zero duplicates, gap-checked), plus a 2025 reload. Exness tick data pulled, validated against Dukascopy (mid-price matches, spread ~2.5x wider on Dukascopy — decision: train price on Dukascopy, simulate cost via Exness-realistic spread model). A real Exness timestamp bug (seconds mislabeled as milliseconds, causing a ~9M-row false "duplicate" count) was found via audit, fixed, and reloaded — confirmed clean via spot-check. `spread_model.py` built: two-tier (flat baseline + event-spike overlay), refined to a curated 11-event-type whitelist. News calendar loaded (115,627 events, 2019–2026). DXY data sourced later (data section below) after catching and fixing a placeholder-data bug in an early pull.

**Open from Phase 1, still relevant:** `SPIKE_TEMPLATE`'s spike shape was calibrated on exactly one NFP event — Metric J (below) partially validated this against other event types, but full tick-level validation is still outstanding.

## Phase 2: Baseline Profiler — ✅ Complete, fully verified
- Session range profile (asian/london/ny mean/median/std/percentiles): trusted.
- Volatility rhythm profile: a bucketing bug (DuckDB `(x/15)::INT` rounds instead of truncating) was found and fixed; independently spot-checked afterward (three checks all passed, including an exact match on independently-recomputed buckets).
- Level-reaction: went through 5 rounds of root-caused bugs before reaching a trustworthy original result, then required a further rebuild (`level_reaction_v2.py`) when a price-regime bug was found — fixed $10 level spacing broke down as gold moved from ~$1,300–2,600 (2019–2024) to $3,000–3,700+ (2025). Rebuilt with **price-relative tiering** (tier1 <$3,000: $10/50 spacing; tier2 ≥$3,000: $25/100 spacing), logic extracted into a shared `level_reaction_core.py` module.

---

## Phase 3: Test 1 — ✅ Resolved, all 12 metrics

### Methodology note — read this before trusting any individual metric below
A significant mid-phase correction happened: several early metrics (A, G, and the original version of I) reported "beats naive/majority" based on **raw win-counts across a 6-combo walk-forward window matrix, with no significance testing**. This methodology was proven to produce false positives when Metric I's original result (claiming volatility clustering vanishes at H1) was traced to a labeling artifact and fully reversed under a corrected test. Following that, Metrics A, C, D, G, H, and I were **re-tested** with real baselines, effect sizes, and bootstrap significance/permutation tests. **The verdicts below are the corrected ones** — where a metric's status differs from an earlier session's first-pass result, the version below supersedes it.

### A — Range prediction: **WITHDRAWN (was a false positive)**
Original: predicted range as % of prior close, claimed to beat naive lag-1. **Retested** (`range_prediction_v3_baselines.py`) against real baselines — 5-session and 20-session trailing % ranges, not just naive lag-1 — scoring every model on identical test days, with bootstrap CI/p-values instead of a binary flag.
- **Asian:** model significantly *worse* than both trailing baselines, all 6 combos (~19–24% worse than the 20-session baseline). Even the 5-session baseline beats it. Gap grows with longer rolling training windows — consistent with a "long-run average adapts too slowly" explanation.
- **London:** no significant difference in any combo.
- **NY:** baseline ahead in every combo; significant in 4/6 (fixed UTC hours) or 2/6 (local/DST-adjusted hours) — borderline (p≈0.05), treat as weak evidence not strong.
- **What survives:** the percentage-of-price *form* is still correct (the baseline used it too). What doesn't survive is training-mean averaging over a long window — recent trailing ranges predict tomorrow at least as well, consistent with real volatility clustering.
- **Recommendation for Phase 4/5:** use a 5–20 session trailing %-of-prior-close range, not a long-window training-mean model — especially not for Asian.
- **Caveat:** the 6 window combos still overlap heavily (robustness-to-window-choice, not independent replication); Asian preferring the 5-session over 20-session baseline was not pre-committed — don't build on that specific ordering yet.

### B — Level-reaction predictive value: **NULL, holds**
Tiering (see Phase 2) correctly fixes a real touch-detection frequency artifact (confirmed: 3–8x inflation at fixed $10 spacing above $3,000). But across every walk-forward test run (single-split, then a 6-combo pre-committed matrix), the tiered model has **never** beaten a simpler pooled-soft model at predicting reject/break/consolidate outcomes. Best current explanation: tier2 (≥$3,000 prices) still has far less training history than tier1 (5,372 vs 656 touches) — an "insufficient data" result, not proof tiering can never help. **Use tiering for detection correctness only, not yet for confidence scoring.**

### C — Volatility regime classification: **CONFIRMED, Asian-session only**
Regime labeled via rolling percentile rank (20th/80th, causal — never a fixed boundary). Original test (single 100-day lookback) showed Asian robust across all window combos, London/NY conditionally real with 3+ year rolling windows. **Retested across lookbacks 60/100/150 days:**
- **Asian:** real and material at lookback 100 (+3.3% Brier gain, 6/6 combos) and 150 (+2.8%, 4/6), but *not* at 60 (+0.7%, 0/6) — moderate evidence (2 of 3 lookbacks), not the clean sweep first reported.
- **London/NY:** effectively nothing — gains sit near zero across 18 tests; one isolated "+" is chance-level. **The earlier "3+ year rolling window" claim for London/NY is withdrawn.**
- **Working hypothesis** (unconfirmed but consistent with A/G): Asian volatility is smooth and persistent; London/NY volatility is spiky and event-driven, so yesterday's session-level regime carries little information there — even though intraday volatility clustering is real for those sessions (see Metric I).

### D — Hurst / trend-mean-reversion character: **NULL (was a measurement artifact)**
Original test showed 17/18 combos with "modest persistence" — later understood to be **mostly a stickiness artifact** from overlapping 60-day Hurst windows (a follow-up check found 87.4% of day-to-day labels were mechanically near-identical). A stride-based fix reduced but didn't fully resolve the concern. **Full redesign** (`trend_character_v3.py`) using rank correlation between non-overlapping 10-day blocks found: rank correlation ≈ −0.02 for both H1 and M30 (95% CIs straddling zero), permutation p≈0.8, and only ~4–5% of blocks show a significant trend/mean-reversion signal — indistinguishable from a random walk at this horizon. **Verdict: no evidence of trend-character persistence.** Test covered one horizon (4 hours) and one block length (~10 days) — doesn't rule out effects at other scales, and says nothing about whether individual breakout setups work through other mechanisms (a Test 2 question).

### E — Distribution shape stability: **Descriptive, holds**
No naive baseline by design. Train-period skew/kurtosis of daily range ratios are consistently high (expected — range is a bounded, fat-tailed statistic), but test-period values are **highly unstable across folds** (Asian test kurtosis ranged from 0.192 to 52.515 across different folds — a real finding about gold's tail behavior changing character over time). Consistent session ordering: **NY most stable, Asian least stable, London in between.** Implication for Phase 4/5: apply session-dependent caution to any position-sizing logic assuming stable tail risk — least confidence in Asian, most in NY. **Script audit still outstanding.**

### F — Weekend gap behavior: **NULL, holds**
No overlapping-window concern (discrete weekly events). Gap regime (small/normal/large, via rolling percentile) shows **0/6 combos** beating naive majority — naive wins every time. Weekend gap size shows no week-to-week persistence. A clean, trustworthy negative finding.

### G — Session-open prediction: **WITHDRAWN (was a false positive)**
Same structure as Metric A (percentage-of-prior-close model vs. naive), same weak-baseline problem. Original result: London/NY robust 6/6, Asian 5/6. **Retested with proper baselines** (`session_open_prediction_v3.py`) — the positive claim does not hold up; withdrawn, consistent with Metric A's correction.

### H — Anomaly-flagging precision: **CONFIRMED, moderate**
Two halves: (1) an opening-30-min-range volatility spike flag, and (2) a calendar-proximity flag (importing `spread_model.py`'s actual event whitelist, not a reimplementation). Original test showed strong results in both halves across all sessions (Asian ~3x precision lift on the volatility half; London ~1.7x, NY ~2.2x on the calendar half — Asian correctly showing zero event-days, since US releases don't fall in that UTC window). **Re-verified** (`anomaly_flagging_v2.py`) — holds, but more moderately than the original numbers suggested.

### I — Cross-timeframe consistency: **FULLY REVERSED**
This is the metric that triggered the mid-phase methodology correction for the whole project.
- **Original test:** D1 and H4 robust (6/6 combos beating majority), M30 mixed (4/6), H1 essentially no signal (1/6) — led to a design recommendation of "build volatility-clustering confidence at D1/H4 only, avoid H1."
- **Problem found:** the regime labels were **time-of-day contaminated** — a bar's label mostly reflected *what hour it was*, not real volatility state (diagnostic: P(label="high") ranged from 0.04 to 0.69 depending on the hour before the fix; flat at ~0.21–0.25 after deseasonalizing). This alone explains most of the apparent "H1 has no signal" result — finer timeframes have more time slots, so the contamination gets worse as granularity increases, exactly matching the original pattern.
- **Corrected test** (`cross_timeframe_consistency_v2.py`): labels ranked only against the same time-of-day slot's trailing history, tested at three lags (previous bar, same slot previous day, ~23 trading days back — the original horizon). Result: **intraday persistence is real and strongest at short lags** — previous-bar and same-slot-previous-day both significant in all 6 combos at H4, H1, *and* M30 (Brier gains of +4–6%, strongest at the finest timeframes: H1 +4.9%, M30 +6.1%). At the original ~33-day lag, the effect is negligible everywhere (+0.1–0.2%). D1's result is now weak and unresolved (+0.54% at lag-1, not significant) — oddly weak next to the intraday results.
- **Design implication — supersedes the original:** intraday regime confidence should be built at **short lags** (previous bar / same time-of-day slot), not at long horizons, and works across H1/M30/H4 — not just D1/H4. **The earlier "avoid H1" guidance is withdrawn.**

### J — Catalyst magnitude prediction: **Partially confirmed, one item open**
Closes the Phase 1 spread-template debt. Found and fixed a genuine multi-stage duplication bug along the way: the raw event whitelist has 979 rows but only 494 distinct release timestamps (CPI/PCE/FOMC each publish several co-named sub-metrics simultaneously) — two different dedup approaches (before vs. after the price join) converged on the same correct 426-event final dataset, a useful cross-check.
- **Part 1 (closes the Phase 1 debt):** NFP's magnitude (mean 0.00365) is significantly different from other event families (p<0.0001). Real ordering: **NFP (0.00365) > CPI (0.00328) > FOMC (0.00253) > GDP (0.00150) ≈ PCE (0.00124)**. Applying the NFP-derived `SPIKE_TEMPLATE` uniformly overstates the spread spike for GDP/PCE specifically, moderately for FOMC, roughly fine for CPI.
- **Part 2:** a per-family average magnitude beats a pooled (family-blind) naive average in all 6 window combos (~5–10% MAE reduction) — confirms the fix is worth making, not just diagnosing the problem.
- **Recommendation, not yet implemented:** split `SPIKE_TEMPLATE` by release family (NFP/CPI/FOMC roughly full-strength, GDP/PCE roughly half-strength).
- **⚠️ Still open:** direct validation against Exness tick-level data before actually changing the template in code — needed to confirm the magnitude-level finding translates correctly into the spread model's spike *shape*, not just its average size.

### K — DXY correlation-regime tracking: **CONFIRMED, real and robust**
Built after sourcing and carefully validating DXY data (see Data Sourcing section below).
- 101 ten-day blocks of hourly gold/DXY returns: mean correlation −0.455 (10th/90th percentile −0.69/−0.19). 94% of block-to-block variation exceeds pure sampling noise.
- Persistence: one block's correlation predicts the next at Spearman +0.648 (95% CI +0.47 to +0.77, permutation p<0.001).
- Per-year: −0.42 (2021 H2) / −0.48 / −0.60 / −0.41 / −0.31 (2025, weakest) — a possible gold-DXY decoupling trend in 2025, unconfirmed (no rigorous external source checked yet).
- **Critical control test** (`dxy_k_vol_control.py`): is this persistence just a volatility-regime effect (since DXY volatility itself is partly a *result* of the coupling)? The clean test — controlling for **gold** volatility only — shows persistence survives essentially intact (+0.606 vs. the raw +0.648, still p<0.001). Gold volatility explains only 3% of block-to-block correlation variance; DXY volatility only 10%. **Verdict: correlation regimes are a genuine, distinct phenomenon — confirmed, fully resolved.**

### L — DXY lead-lag alignment: **NULL — no usable predictive signal**
Built alongside K, after a dedicated **timestamp alignment check** (`dxy_alignment_check.py`) confirmed the gold and DXY feeds are genuinely clock-aligned (correlation peaks exactly at lag 0, both winter and summer, both series correctly peaking at the known NY 8:30/10:00 release times) — ruling out an MT5 server-time offset that could have silently corrupted this metric.
- Contemporaneous correlation is strong: −0.38 overall, −0.66 in the NY 08:25–08:45 release window.
- **All lagged correlations are essentially zero** (≤0.011 in magnitude) at every tested lag from −10 to +10 minutes, overall and both inside/outside the release window.
- The only detectable asymmetry is a statistically real but economically negligible 1-minute gold-leads-DXY effect (~0.01% of variance) — plausibly explained by DXY being a synthetic FX-quote-derived index that updates a beat later.
- **Verdict:** DXY is not a leading indicator at retail latency. It's a strong *simultaneous* read on whether a gold move is dollar-driven — a filter idea for Phase 4 setup logic, not a predictive signal.

---

## Data Coverage Gap
Gold minute data currently ends **2025-12-31**; DXY data runs to **2026-09-21**. Every Test 1 metric except K/L (which use the DXY/gold overlap, 2021-07-19 to 2025-12-31) is based on 2019–2025 data only — **nothing above has been tested against 2026 data yet.** Open, undecided question: deliberately hold out the 2026 Exness data as a genuine unseen final-confirmation set for the key findings — it's a different feed from the Dukascopy data everything above was trained on, so this needs careful handling, not a casual reuse.

## DXY Data Sourcing — validated, for reference
- `dxy_d1_ohlc`: 2,361 daily bars, 2019-03-01 to 2026-09-21.
- `dxy_m1_ohlc`: 1,921,828 intraday bars, 2021-07-19 to 2026-09-21 (earlier history unavailable at minute resolution).
- **A real defect was caught and fixed along the way:** an early M1 pull contained placeholder (non-real) data for part of its range; fixing it initially also accidentally deleted the only daily-resolution source alongside the bad intraday data — caught and corrected before it could propagate into K/L.
- Final validation: zero flat (open=high=low=close) bars, and the year-by-year close-price trajectory matches real DXY history closely (~97–98 in 2019, dropping to ~89 during 2020–2021 COVID-era dollar weakness, surging to a 114.12 high in 2022 matching the real Fed-hiking-cycle multi-year high, settling 100–108 through 2023–2025) — confirmed genuine, not synthetic or corrupted.
- Timestamp alignment with gold confirmed clean (see Metric L above) — no clock offset, no DST-driven drift.

## Open Items, in priority order
1. **Metric J tick-level spread validation** — last open Phase 3 item, needed before implementing the `SPIKE_TEMPLATE` release-family split
2. Decide on the 2026 Exness holdout question
3. Script audits for Metrics E and J
4. DST/daylight-saving check for Metrics B and E specifically — session-boundary correctness around clock changes already proved material for Metrics A and I
5. Begin Phase 4 (the 10 setups) design — every confirmed/withdrawn finding above is now a real, evidence-based design constraint, not a placeholder assumption

## Phase 4: The 10 Setups — ⬜ Not started
## Phase 5: AI Decision Layer — ⬜ Not started
## Risk Controls — ⬜ Not started (build in parallel with Phase 4, not after)

## Standing Lesson, Worth Carrying Into Every Future Phase
The single most important methodological finding of Phase 3 isn't any individual metric — it's that **"beats naive/majority" claims built on raw win-counts without a real baseline and a significance/effect-size check produced multiple false positives** (Metrics A, G, and the original version of I). Every one of those was only caught by deliberately going back and re-testing with harder, more honest comparisons. Apply the same discipline to Phase 4 setup backtesting and Phase 5's AI confidence scoring from the start, rather than discovering the same failure mode a fourth time.
