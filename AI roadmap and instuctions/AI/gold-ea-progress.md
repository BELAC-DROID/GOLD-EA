# Gold EA Project — Progress & Preferences

*Last updated: 2026-09-21 (added external validation review; fixed 9/12 vs 10/12 count) - previously 2026-09-20 (fixed stale internal contradictions left over from incremental edits — see note below)*

## Project
Building a gold trading EA for MetaTrader 5, with a layered AI decision system on top — infrastructure/data pipeline first, then a baseline profiler, then the trading setups, then the AI edge-mining layer last.

## Agreed Build Order
1. Infrastructure + data pipeline — ✅ done
2. Baseline profiler — ✅ done
3. Calibration checkpoint tests (Test 1) — 🔄 in progress, 10/12 metrics done (corrected methodology; count fixed 2026-09-21 - body lists A-J done, K/L remaining)
4. The 10 trading setups — not started
5. AI decision layer — not started

## Infrastructure — ✅ Functionally complete
Windows Server 2022 VM on Oracle UK South, Python↔MT5↔Exness verified, timezone clean, 6 years of Dukascopy data + Exness sample loaded, spread model built, calendar loaded, `analytics.duckdb` built with OHLC bars across all standard timeframes.

**This session's finding:** `audit_ticks.py` caught a real bug in the Exness load — `timestamp_utc_ms` was stored in **seconds, not milliseconds** (a pandas datetime-resolution issue), which also explained an apparent 9M "duplicate timestamps." **Fix confirmed** via a direct re-audit: date range now correctly shows 2026-01-01 to 2026-09-18, duplicates dropped to 1,024,603 (~1.44% of rows, spot-checked and confirmed genuine same-millisecond quote updates with distinct bid/ask). No open items remaining on this fix.

## Phase 2 (Baseline Profiler) — ✅ Complete and fully verified
- Session range profile: ✅ trusted
- Volatility rhythm profile: ✅ trusted — bug fixed earlier, independently spot-checked this session (three checks all passed, including an exact match on independently-recomputed buckets)
- **Level-reaction: found and fixed a second real bug, now confirmed.** The original 4,945-touch result used a fixed $10 level spacing, which doesn't hold up as gold's price moved from ~$1,300–2,600 (2019–2024) to $3,000–3,700+ (2025). Rebuilt with **price-relative tiering** (tier1 <$3000: $10/50 spacing; tier2 ≥$3000: $25/100 spacing). Confirmed result: 5,372 touches/2.78 per day under $3,000 (reject 32.1%/break 29.0%/consolidate 38.8%) and 656 touches/2.63 per day at $3,000+ (reject 31.2%/break 28.5%/consolidate 40.2%) — percentages closely match the old result and touches/day is now comparable across tiers, confirming the fix worked correctly.

## Phase 3 (Test 1) — 🔄 In progress, 10 of 12 metrics done
**[SUPERSEDED 2026-09-21 - see 'Metric I v2 results' at end of file]** **Metric I (cross-timeframe consistency), extended to all 4 available timeframes (H1/H4/M30/D1):** clean, monotonic finding — D1 and H4 both robust (6/6 beats majority), M30 mixed (4/6), H1 essentially no signal (1/6, model≈majority). Volatility clustering weakens steadily with finer granularity and vanishes at H1. Build confidence signals at D1/H4 only in Phase 4/5 — H1-resolution regime confidence isn't supported by this data.

**Metric H (anomaly-flagging precision), both halves:** volatility-spike flag beats base rate in all 18 tests, Asian strongest (~3x lift) — good counter-example showing Asian isn't universally weak, just weak specifically for percentage-of-price/long-rolling-window models (Metrics A/G). Calendar-proximity flag correctly shows 0 event-days for Asian (US releases don't fall in that UTC window — expected), robust ~1.7-2.2x lift for London/NY.

**Metric E (distribution shape stability):** descriptive finding — gold's tail behavior genuinely changes character over time (Asian test kurtosis swung from 0.192 to 52.515 across folds). NY most stable, Asian least stable, London in between. Apply session-dependent caution in Phase 4/5 risk logic.

**Metric G (session-open prediction):** London/NY beat naive in all 6 combos. Asian beats naive in 5/6 (razor-thin loss in rolling_4yr_test1yr). **Notable:** same session/long-rolling-window weakness already seen in Metric A — two metrics now confirm percentage-based Asian-session models degrade under longer rolling training windows specifically.

**Metric C (volatility regime classification):** Asian session beats naive majority in all 18 tested configs — confirmed robust. London/NY: real but conditional signal, only detectable with 3+ year training windows. Design implication: default to 3+ year windows for London/NY regime confidence in Phase 4/5.

**Metric D (Hurst/trend character):** first version looked dramatic but was a measurement artifact — 87.4% of day-to-day labels were mechanically identical due to a 60-day overlapping window. Fixed by testing 20-day-apart transitions instead. Final: real but modest persistence (17/18 combos beat majority), with an honest caveat that residual window overlap likely still inflates the effect somewhat — weight this lower than Metric C's cleaner Asian result.

**Metric F (weekend gap):** clean negative result, no artifact concerns — gap size shows no week-to-week persistence (0/6 combos beat majority).

**Metric B (level-reaction) done, robustly confirmed:** a pre-committed 6-combo window matrix (same as Metric A) shows the tiered model never beats the simpler pooled-soft baseline, in any combo — strongly confirms tiering helps touch-*detection* correctness but hasn't demonstrated predictive value (still attributed to tier1 vastly outnumbering tier2 in the data).

**Metric A (range prediction):** rebuilt to predict range as a **percentage of prior close** (fixing the same fixed-dollar bug). **Update — re-tested against a pre-committed 6-combo walk-forward matrix** (expanding_test1yr/6mo, rolling_2/3/4yr_test1yr, rolling_3yr_test6mo — the same matrix later applied to Metric B), stepping forward through the full 2019–2026 dataset with multiple pooled folds per combo, not just 3 anchor splits: **London and NY beat naive in all 6 combos, no exceptions** — as robust a result as this kind of testing can give. **Asian is genuinely fragile, not just weaker:** beats naive in 4/6 combos (both expanding schemes, rolling_2yr, rolling_3yr_test6mo) but **loses to naive specifically in rolling_3yr_test1yr and rolling_4yr_test1yr** — a real, reproducible pattern (longer *rolling* windows hurt Asian specifically), not noise from one bad split. Working theory (flagged as inference, not confirmed): Asian's range/prior-close ratio may drift more over multi-year spans than London/NY's, so long trailing averages smooth past a signal that shorter or continuously-updated windows still catch.

**[SUPERSEDED 2026-09-21 - see 'Metric A v3 re-test results' at end of file]** Revised verdict (old): trust the percentage model for London and NY. Treat Asian as **unproven**, not just mildly weaker — don't lean on this model's confidence for an Asian-session Phase 4 setup yet.

**Result:** a genuine, honest tradeoff — the percentage model cut error by ~30–35% in the 2025 test period (the case that matters most for how Phase 4 setups will actually trade), but is mildly worse than the old fixed-dollar model during the more stable 2023 test period. Judged worth taking given gold's price level keeps shifting, not settling.

**Bigger-picture pattern worth remembering:** three bugs now (level spacing, range prediction, and the level-reaction *walk-forward test itself*) have traced to the same root cause — a fixed-dollar assumption breaking as gold's price level changes. Worth explicitly checking for this same trap in the remaining metrics before building them.

**Metric B (level-reaction), window-matrix update:** the single-split "doesn't beat pooled-soft" finding is now confirmed robust across the same 6-combo matrix, not a one-off — model Brier lands in a tight 0.6630–0.6640 band vs. pooled-soft's 0.6617–0.6625 in **every single combo**, with tiering never once gaining an edge. Same explanation as before (tier1's 5,372 touches vastly outnumber tier2's 656, diluting any tier2-specific signal regardless of window scheme) — just now backed by 6 independent tests instead of 1. **Conclusion stands, on firmer ground:** keep tiering for touch-*detection* correctness (it fixed a real measurement bug), don't yet trust it for prediction *confidence*.

**Metric J (catalyst magnitude) — ✅ done, closes a real Phase 1 debt item.** Tests whether `spread_model.py`'s NFP-derived `SPIKE_TEMPLATE` (calibrated on exactly one NFP event, applied uniformly to all 11 whitelisted event types) is actually a reasonable stand-in for every event type. Went through 3 debugging rounds on event-count deduplication: v1 didn't dedup calendar events sharing an exact release timestamp (CPI/PCE/FOMC families routinely publish multiple named sub-metrics at once — 979 raw rows, only 494 distinct timestamps) → inflated to 2,595 rows. v2 deduped *after* joining to price data, by which point the duplicate timestamps had already fanned out combinatorially in the join → still wrong (426, should be ≤494). v3 fixed it by deduplicating the events table *before* any price join. Interestingly, v2 and v3's final numbers matched byte-for-byte anyway — the duplicate rows all carried identical underlying price values, so post-hoc dedup accidentally landed on the same answer as pre-hoc dedup (confirmed via two independent code paths, not just assumed).

**Final result: 426 usable events, ±2min pre / +8min post-release price moves, grouped by release family (NFP/CPI/FOMC/GDP/PCE).** Part 1 (does NFP's shape generalize?): **No — confirmed with p<0.0001.** Magnitude ordering: NFP (mean 0.365% of price) > CPI (0.328%) > FOMC (0.253%) > GDP (0.150%) ≈ PCE (0.124%). GDP and PCE move gold less than half as much as NFP; CPI is the closest match to NFP, FOMC moderately overstated by the current template. Part 2 (does knowing the family actually help predict magnitude?): **Yes — per-family average beats pooled naive in all 6 window-matrix combos**, ~5–10% MAE reduction consistently. **Concrete recommendation, not yet implemented:** split `SPIKE_TEMPLATE` by release family — keep NFP/CPI/FOMC near full strength, scale GDP/PCE to roughly half strength — rather than applying one NFP-shaped template to all 11 event types.

**Status:** 10 of 12 metrics done, all on corrected, robustness-tested methodology (Metrics A and B specifically re-verified against a shared 6-combo walk-forward matrix, not just single splits). **Remaining 2:** DXY correlation-regime tracking and DXY lead-lag alignment (Metrics K/L) — both need DXY historical data sourced first, not yet pulled.

**New concrete design implication from Metric A's window-matrix update:** don't treat the Asian-session percentage-based range model as trustworthy — it fails specifically under long rolling training windows (3-4yr), a real structural weakness, not noise. Any Asian-session Phase 4 setup should not lean on this model's confidence yet.

**New concrete action item from Metric J:** `spread_model.py`'s `SPIKE_TEMPLATE` should be split by release family (NFP/CPI/FOMC near full strength, GDP/PCE at roughly half strength) rather than applying one NFP-derived shape to all 11 whitelisted event types — confirmed with p<0.0001 that NFP's magnitude doesn't generalize, and confirmed the family split actually improves prediction (beats naive in all 6 combos). Not yet implemented in spread_model.py itself.

**Caveat worth carrying forward:** Metrics C through J were built and verified in a separate session/thread from the one that fixed the Exness/level-spacing/range-prediction bugs. This document summarizes their results, but the underlying scripts haven't been independently reviewed the way `level_reaction.py` was — worth a real audit before leaning hard on any one of them for a Phase 4 design decision, given this project has now found the same fixed-dollar-assumption bug three separate times.

See `gold-ea-roadmap.md` for full detail, the complete walk-forward results table, and the exact outstanding confirmation items.

---

## External Validation Review (added 2026-09-21)

Web/literature review of whether the Phase 1-3 methodology and results match expert practice. **Source-quality caveat:** mostly academic papers plus broker/educational blogs (weak evidence); only two real trader-forum threads found (StrategyQuant, Tickstory). Reviewer saw the progress file and the pasted session transcript only - **not the scripts, the roadmap, or the AI-decision-layer file**, so nothing below is a code audit.

**Verdict:** process is unusually rigorous for a retail EA project, but several conclusions are stated more strongly than the evidence supports, and a few will likely change under harder tests. Everything so far validates *statistical properties*, not a tradeable edge.

### What holds up well
- **Walk-forward as the core method** - still the industry standard for realistic trading simulation; anchored + rolling variants match the two standard types.
- **Pre-committing the window matrix** before seeing results - guards against "implicit fitting" (subjective choices made after seeing outcomes contaminating the test).
- **Data auditing** - catching the seconds-vs-ms Exness bug and the placeholder DXY M1 data is exactly the data-quality discipline practitioners warn about.
- **Dukascopy history + Exness spread model** - matches forum practice (price/range data from Dukascopy, spreads/slippage from the actual broker).
- **Catalyst ordering (Metric J)** NFP > CPI > FOMC > GDP/PCE is consistent with published high-frequency work (payrolls ~6x volatility increase, GDP/CPI/FOMC ~3-4x). That study is equity futures, not gold - supporting evidence only.

### Where results are overstated or need harder tests
1. **Metric A baseline is weak.** "Naive" = yesterday's range (one noisy observation); any smoothed average beats it. Re-test against a trailing 5-20 day mean range (ATR-style) and/or a HAR-type model. London/NY "beats naive in 6/6" may shrink. *(Reviewer's own knowledge, untested.)*
2. **Metric B has no demonstrated predictive value.** Pooled-soft Brier (~0.662) is essentially the floor for the 32/29/39 class split, so both models ~= base rates. Conclusion (keep tiering for detection only) stands, but headline should be "features don't predict outcomes yet."
3. **The 6 window combos are not 6 independent tests.** Test periods overlap heavily (first three combos share identical test counts, 4,239). The matrix shows robustness to window choice, not replication. Wording "6 independent tests" above should be read as overstated.
4. **Win counts are not significance tests.** Asian "fragility" margins are ~1.5-3% MAE and its wins are equally thin (rolling_2yr wins by ~0.7%). No significance test on A/B/C/D/E/F/G/H/I; only Metric J has one (Welch). Multiple-testing burden: 12 metrics x 3 sessions x 6 combos - some "findings" will be luck (literature suggests t-stat hurdles nearer 3 than 2). Fix: block-bootstrap or Diebold-Mariano tests.
5. **Metric J measures price moves, but SPIKE_TEMPLATE is a spread shape.** Price magnitude and spread widening are related, not proportional. Validate the family split against measured spreads (Exness sample, 2026 only) before editing spread_model.py. Also: 8-min post window probably understates FOMC (slower volatility decay than payrolls); t-test assumes normality on skewed data (use Mann-Whitney/bootstrap); GDP/PCE mix multiple estimate releases and may coincide with other same-time releases.
6. **Metric I "clustering vanishes at H1" contradicts the literature.** Volatility clustering is one of the most robust findings in finance; strong intraday time-of-day seasonality (varies >5x) can mask it if not removed. Suspect the method (was time-of-day removed before defining regimes?) before concluding H1 has no regime signal. Do **not** yet bake "D1/H4 only" into Phase 4/5 on this basis.
7. **Metric D (Hurst).** Rescaled-range estimates are biased (toward ~0.7) and need large samples; generalized Hurst (GHE) / DFA are lower-bias. Confirm which estimator was used. Existing low weighting is correct.
8. **Session windows in fixed UTC** (Asian 0-8, London 8-16, NY 13-21). London/NY opens shift an hour with DST, and UK/US switch on different dates. Confirm handling - can quietly blur every per-session result.

### Guidance for Metrics K / L (DXY)
- Correlate **returns, not price levels** (levels overstate the relationship). Window/threshold choices (20-90 bars, 0.3-0.5) are conventions, not standards - don't import a threshold; derive from your data.
- Published gold-DXY "baselines" disagree wildly (~-0.45 on 30-day windows vs ~-0.85 on 60-month windows). Use your own data.
- Relationship can flip in systemic crises (e.g. 2008, Mar 2020); test whether a correlation regime *persists* out of sample, same as other metrics.
- DXY is ~57.6% EUR - behaves close to inverted EURUSD.
- **Lead-lag (L):** biggest risk is timestamp alignment between the Dukascopy gold feed and the broker DXY feed; a 1-minute offset can manufacture a fake "DXY leads gold" result. Verify alignment first (e.g. against a known event timestamp).

### Phase 4 cautions
- Falsification study on index futures (MNQ): post-news drift was entirely inside the first few bars after release; from bar +6 onward T-stats were ~0.1-0.7. Don't assume a tradeable post-news continuation edge in gold - analogy only.
- Phase 4 needs P&L tests with realistic spreads/slippage and a running count of how many setups/parameters were tried (deflated-Sharpe / probability-of-backtest-overfitting logic).

### Action items (ordered by cheapness / likelihood of changing a conclusion)
- [x] Re-run Metric A vs trailing-mean-range baseline, all 6 combos (done 2026-09-21; HAR not yet tried)
- [ ] Add block-bootstrap / Diebold-Mariano significance to A, B, C, G, I; report p-values, not win counts
- [x] Metric I: time-of-day removed and re-tested (done 2026-09-21 - see v2 results; conclusion changed)
- [ ] Verify session windows vs DST (London/NY) in all per-session scripts (done for Metric A only - see v3 results; remaining metrics still to check)
- [ ] Measure spread widening directly around events (Exness sample) before splitting SPIKE_TEMPLATE
- [ ] Confirm Hurst estimator; consider GHE/DFA
- [ ] Before Metric L: verify DXY/gold timestamp alignment
- [ ] Independent code audit of Metrics C-J scripts (already flagged above)

### Sources consulted
- Walk-forward / overfitting: https://arxiv.org/pdf/2512.12924 ; https://arxiv.org/pdf/2406.18206 ; https://surmount.ai/blogs/walk-forward-analysis-vs-backtesting-pros-cons-best-practices ; https://fxexpertadvisors.com/mt4-ea-optimization/
- Multiple testing: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253 ; https://arxiv.org/pdf/2603.20319
- Intraday volatility / announcements: https://arxiv.org/pdf/1211.2961 ; https://quanthedge.substack.com/p/seasonality-of-intraday-volatility
- Post-news drift (MNQ): https://arxiv.org/pdf/2605.04004
- Hurst estimators: https://arxiv.org/pdf/cond-mat/0010211 ; https://www.researchgate.net/publication/223563414_A_comment_on_measuring_the_Hurst_exponent_of_financial_time_series
- Data/spread practice (forums): https://strategyquant.com/forum/topic/spreads-and-slippage-for-different-cfds-and-testing-for-robustness/ ; https://tickstory.com/forum/viewtopic.php?t=3041
- Gold-DXY correlation: https://www.luxalgo.com/library/concept/dxy-correlation-regimes/ ; https://copi-tools.com/blog/gold-dollar-correlation/ ; https://fazencapital.com/learn/en/gold-dxy-correlation-trading-xauusd ; https://www.pro-scalper.com/gold-market/gold-dollar-dxy-correlation

---

## Metric A v3 re-test results (added 2026-09-21)

Script: `backtest\range_prediction_v3_baselines.py` (results CSV: `range_prediction_v3_results.csv`). Same 6-combo window matrix; all models scored on identical test days; pre-committed primary comparison = percentage model (training-mean range/prior-close x prior close) vs trailing-20-session mean ratio x prior close (`trail20_pct`). Circular block bootstrap (block 10, 2000 resamples) on paired absolute-error differences. Two session definitions tested: `fixed_utc` (original) and `dst_aware` (London/NY 08:00-16:00 local; Asian fixed UTC).

**Result: the percentage model's earlier "beats naive" wins came from the weak baseline (yesterday's single range), not from the model.**
- **Asian:** percentage model is *significantly worse* than the trailing-20 baseline in all 6 combos (MAE ~6.5-8.4 vs ~5.4-6.7; ~19-24% worse). Even trailing-5 beats it. The gap widens with longer rolling windows (+1.04 -> +1.64). Interval coverage also degrades under rolling windows (80% interval covers only ~73-76%; 90% covers ~84-87%; expanding windows are ~0.81/0.90). Consistent with the drift theory in the old notes: a fixed training-mean ratio is too slow to adapt.
- **London:** no significant difference vs trailing-20 in any combo, either session definition. All point estimates slightly favor the baseline (+0.09 to +0.50 MAE). Coverage near nominal (80%: 0.79-0.85; 90%: 0.90-0.93).
- **NY:** point estimates favor the baseline in every combo; significant (borderline, p ~0.03-0.06) in 4/6 under fixed UTC and 2/6 under DST-aware. Coverage near nominal.
- **Interpretation:** for London/NY the percentage model is roughly equivalent to a 20-session trailing average - it adds nothing beyond it. Recent ranges predict tomorrow's range at least as well as a long-run average ratio (consistent with volatility clustering). The percentage-of-price *form* is still right (the trailing baseline used it too); the long-window training-mean *estimator* is what doesn't earn its place.
- **Session definition:** switching fixed-UTC -> DST-aware does not overturn the conclusion. Side observation (reasoning, not tested): the fixed 13:00-21:00 UTC NY window starts after 12:30 UTC, when 08:30 US releases (NFP/CPI) print during US daylight time, so it likely misses those releases for roughly half the year. The DST-aware NY ranges are larger (MAE ~8.8 vs ~8.4). Matters for any catalyst/session logic and for the remaining per-session metrics.

**Revised Metric A verdict:** use an adaptive trailing-range estimate (5-20 sessions, as % of prior close) as the range baseline for Phase 4/5, not the long-window training-mean ratio. Do not use the training-mean model for Asian at all. Caveats: two of the three "significant" NY results sit right at the p~0.05 boundary; the 6 combos overlap heavily (robustness, not replication); trailing-5 vs trailing-20 preference differs by session (Asian favors shorter, London/NY longer) but was not pre-committed - don't cherry-pick it; HAR-type models and volatility-clustering models (GARCH-style) not yet tried; coverage here uses unconditional quantiles, so near-nominal coverage shows stability, not forecasting skill.

**Remaining from the review's action list:** bootstrap significance for B, C, G, I; Metric I deseasonalized re-test; DST check for other per-session metrics; direct spread measurement before touching `SPIKE_TEMPLATE`; Hurst estimator confirmation; DXY timestamp alignment before Metric L.

---

## Metric I v2 results (added 2026-09-21)

Script: `backtest\cross_timeframe_consistency_v2.py` (CSV: `cross_timeframe_consistency_v2_results.csv`). Tests whether a bar's volatility regime (low/normal/high, 20/80 percentile) predicts the next one, vs the marginal-frequency (majority) baseline, Brier-scored over the same 6-combo window matrix, with block-bootstrap significance. Variants: original method (control) vs time-of-day-adjusted labels (rank vs previous 100 bars of the SAME time slot) at three lags.

**Confirmed on real data: the original labels were dominated by time of day.** P(label='high') by time slot ranged 0.04-0.69 (H1) / 0.04-0.75 (M30) / 0.06-0.64 (H4) with the original labelling; after adjusting it is flat (~0.21-0.26).

**Result: the original Metric I conclusion is wrong and is retracted.** ("D1/H4 robust, H1 no signal, build confidence at D1/H4 only.")
- **Short-lag regime persistence is real at every intraday timeframe** and is largest at the finest: previous-bar Brier gain vs majority M30 +6.07%, H1 +4.87%, H4 +3.95%, all significant in 6/6 combos. Same time slot on the previous day: +1.4-1.8%, 6/6 at all three.
- **~33-day (23 trading days back) persistence is negligible everywhere:** +0.1-0.2% at intraday timeframes (statistically "significant" in some combos only because n is huge - 40k-80k observations), none at D1. Practically zero.
- **The main reason for the original H1 "no signal" was the horizon** (single-bar label vs ~33 days ago), not the labelling: orig vs adjusted labels at the same 33-day lag differ by only ~0.1-0.2%; moving from 33 days to the previous bar moves the gain from ~0.1% to ~5%. Not tested: original (contaminated) labels at short lag - that would show spurious persistence from the daily volatility cycle alone, which is why the adjusted labels are needed to read short-lag results.
- **The old "D1/H4 robust 6/6" was overstated:** those were raw wins by tiny margins with no significance test. In the control D1 gain is +0.39% (1/6 significant), H4 +0.43% (2/6), H1/M30 ~0%. D1 with lag 1 day shows +0.54%, 0/6 significant, but D1 has only ~1,300 pooled test days per combo so power is low - unresolved, and oddly weak vs the intraday results (worth checking against Metric C's daily-session effect sizes).

**Design implications (replace the old "D1/H4 only" guidance):** regime confidence for intraday setups is supported. Use time-of-day-relative regimes (not raw percentile of range), short lags (previous bar / previous session), and don't use monthly-lag regime labels. This shows regime persistence only, not a tradeable edge (Test 2 question). Caveats: 6 combos overlap heavily; time slots are UTC (some residual daylight-saving seasonality); 95% test means an occasional stray "+" is expected by chance.

**Knock-on:** other metrics scored by raw "beats majority" counts (C, D, E, F, G, H) likely share the same problem - tiny effect sizes reported as wins. Apply effect size (% Brier gain) + block-bootstrap CI to them.

---

## Phase 3 status audit after the validation review (added 2026-09-21)

Based on the descriptions in this file, NOT on the scripts for E, G, H (not reviewed). Replaces any "10 of 12 solid" reading of the headline count.

| Metric | Status | Why |
|---|---|---|
| A range prediction | Re-verified (2026-09-21) | Stronger baselines, same-sample scoring, bootstrap CIs. Verdict: percentage model adds nothing over a trailing average |
| I cross-timeframe | Re-verified, conclusion reversed | Time-of-day fix; short-lag persistence real, monthly negligible |
| B level-reaction | Null result, low exposure | Raw win counting inflates positive claims, not nulls; Brier ~ base-rate floor. No CI yet |
| F weekend gap | Null result, low exposure | 0/6 combos; same reasoning |
| J catalyst magnitude | Partly confirmed | Part 1 has a formal test; Part 2 has no CI; not yet validated against spreads (SPIKE_TEMPLATE); FOMC window likely too short |
| C vol regime (positive claim) | PROVISIONAL | Raw win counts, no effect sizes. Re-test script: volatility_regime_classification_v3.py |
| D Hurst (positive claim) | PROVISIONAL | Raw win counts; overlapping 60-day windows need block_len>=60; estimator unconfirmed |
| G session-open (positive claim) | PROVISIONAL | Win counts, margins unknown. Script not yet reviewed |
| H anomaly flags | Lower exposure, still unverified | Reported lifts are large (~2-3x) but no CIs. Script not yet reviewed |
| E distribution shape | Descriptive | Not a win-count metric; kurtosis estimates are noisy under heavy tails |
| K, L (DXY) | Not built | DXY tables validated. K: use returns not levels. L: DXY M1 only from 2021-07-19 and gold/DXY timestamp alignment still unverified |

Tooling: `regime_transition_harness.py` upgraded (effect size + block-bootstrap CI + verdict codes; Brier numbers verified identical to the old harness on synthetic data). Verdict codes: '+' significant and >=1% gain (1% is a judgement call), 't' significant but trivial, '0' none, '-' significantly worse. Note: on a pure-noise process the transition model shows a slightly negative gain (estimation cost of extra parameters), so '-' means "no signal", not "harmful".

### Update: findings from reading the G / H scripts and the Hurst / weekend-gap reruns (2026-09-21)
- **Metric F (weekend gap), rerun on the upgraded harness:** model significantly worse than majority in 5/6 combos (mean gain -2.8%, n_test ~154-254 weekly gaps). Confirms the null (no week-to-week persistence); the negative sign is the estimation cost of the extra parameters on a small sample, not anti-persistence.
- **Metric D (Hurst):** the pasted output was in the OLD harness format (no effect sizes/CIs), so that run did not use the upgraded scoring. From the printed Brier numbers the gains are ~1.4-3.0% (Asian), ~2.3-5.4% (London), ~0-1.2% (NY, one combo loses) - unverified for significance. Bigger issue: labels come from a 60-day window with a 20-day stride, so consecutive labels share 40 of 60 days and persistence can arise by construction. Honest test: stride >= 60 (non-overlapping windows) and block_len >= 60.
- **Metric H, opening-range half - design flaw:** ground truth was the FULL session range, which contains the flagged first 30 minutes (part-whole overlap), so the reported lift (e.g. ~3x Asian) is partly mechanical. Corrected ground truth = range of the rest of the session. Script: `anomaly_flagging_v2.py` (reports both).
- **Metric H, calendar half - design flaw:** events mapped to sessions by fixed UTC windows; US 08:30 ET releases print at 12:30 UTC in summer and 13:30 UTC in winter, so a fixed 13-21 UTC NY window misses summer releases (composition is seasonal). `anomaly_flagging_v2.py` tests both mappings.
- **Metric G (session open):** same structure as original Metric A (training-mean % model vs lag-1), so its "beats naive" result is expected to shrink the way A's did. Script: `session_open_prediction_v3.py`.
- All three new/updated scripts were smoke-tested on synthetic data only. On synthetic noise the original H ground truth produced a false "+" in NY (lift ~1.6x) that disappeared with the corrected ground truth - a demonstration of the mechanism, not evidence about gold.

### Results: Metric G v3, Metric H v2, Hurst script inspection (added 2026-09-21)
**Metric G (session-open prediction) - positive claim withdrawn.** `session_open_prediction_v3.py` on real data: the training-mean percentage model is significantly worse than the trailing-20-session % baseline in 6/6 combos for Asian and for London/NY under DST-aware sessions, and in 4/6 (other 2 no difference) for London/NY under fixed UTC. Same lesson as Metric A: the earlier "beats naive" came from the weak lag-1 baseline. Asian 80% intervals cover only ~69-79% under rolling windows (drift). Use an adaptive trailing estimate (as % of prior close) for opening-range expectations.

**Metric H, opening-range flag - confirmed, with a small overlap effect.** Flag (first 30 min > 90th pctl of previous 100 days) vs corrected ground truth (range of the REST of the session in the top 20%): significant and >=3 points above base rate in 6/6 combos for Asian (precision 0.61 vs base 0.23, lift 2.7x), London (1.8x fixed / 1.9x DST-aware) and NY fixed-UTC (1.8x). NY DST-aware is the weakest: lift 1.4x, significant in only 3/6 combos. The part-whole overlap the original design had is real but modest: lift falls only ~0.1-0.3x when the flagged window is excluded from the ground truth (e.g. Asian 2.82x -> 2.68x). Note: the fixed-UTC NY "open" (13:00 UTC) is 08:00 ET in winter but 09:00 ET in summer, i.e. after the 08:30 releases, so the DST-aware NY figure is the cleaner estimate. Flagged days ~120-130 per combo.

**Metric H, calendar flag - confirmed, with a corrected NY figure.** Significant and >=3 points above base rate in 6/6 combos everywhere with enough events: London lift ~1.7x (358 event-days under both mappings), NY DST-aware 1.81x (precision 0.39 vs base 0.21, 412 event-days). The fixed-UTC NY mapping caught only 178 of those 412 event-days and showed 2.2x - a differently composed subset. Use the DST-aware mapping. Asian: no whitelisted events fall in its window (expected). Caveat: even on flagged days ~60% of sessions are NOT high-volatility - this is a risk indicator, not a predictor; event types are pooled (NFP vs lesser releases not separated); interaction of the two flags untested.

**Metric D (Hurst) script inspection:** `hurst_trend_classification.py` appears to contain two copies of the code (a harness-based section near the top and a standalone section from ~line 52 with its own run_combo/class_freqs/brier). The standalone copy is what ran, which is why the output was in the old format. It uses a rescaled-range estimator (`hurst_rs`) on a 60-day lookback - the biased, small-sample estimator flagged in the review - with a 20-day stride, so consecutive labels share 40 of 60 days. Metric D stays PROVISIONAL until rewritten (single copy, non-overlapping stride >= 60, block_len >= 60, lower-bias estimator).

**Status table changes:** G -> positive claim withdrawn; H -> confirmed (moderate, with the caveats above); D -> provisional, rewrite needed; C -> re-test script written (`volatility_regime_classification_v3.py`), not yet run.

### Metric D (Hurst) - verdict: no evidence of trend-character persistence; replaced (added 2026-09-21)
Script inspection + simulation. `hurst_trend_classification.py` is two scripts pasted together (the standalone second copy is what ran). It uses a single-scale R/S ratio, log(R/S)/log(n), on 60 returns, and compares labels 20 days apart (40 of 60 days shared).
- **Simulation, pure iid t(4) noise, identical labelling and scoring:** the transition model "beats majority" by **+5.9% on average** (range -0.9% to +13% across 20 noise datasets) at stride 20. Real-data results were ~-0.5% to +5.4% - **inside the noise band**. At stride 60 (no overlap) noise gives -3.1%. So Metric D's earlier "modest real persistence, 17/18 combos" was reproducible on noise.
- **Estimator is weakly discriminating:** on 60-return windows iid noise is labelled trending ~30% / mean-reverting ~11% (close to the real-gold label mix: 29-35% / 4-8%); AR(+0.2) only 54% trending, AR(-0.2) only 28% mean-reverting.
- **Power:** ~30 non-overlapping 60-day windows exist in 7 years of daily data - too few to test persistence.
- **Replacement:** `trend_character_v3.py` - Lo-MacKinlay robust variance-ratio z (null-centred at 0) on H1 and M30 returns, ~170-210 non-overlapping ~10-day blocks, Spearman rho between consecutive blocks with bootstrap CI and a within-block permutation null. Validated on synthetic data: detects planted persistent regimes (rho +0.42, p~0), finds nothing in noise. Not yet run on real data. Note: on heavy-tailed data the |z|>1.96 share can run above 5% (~8% for t(4) in a 230-bar block).
- **Implication for the design doc:** drop Hurst-based trend/mean-reversion confidence from Phase 4/5 until the v3 test shows persistence on real data.

### Results: Metric C v3 and Metric D replacement (trend_character_v3) on real data (added 2026-09-21)
**Metric D replacement - no evidence that trend character persists.** Variance-ratio z (4-hour horizon) on ~10-day non-overlapping blocks: rank correlation between consecutive blocks H1 -0.017 (95% CI -0.16 to +0.13, permutation p=0.83, 171 blocks), M30 -0.022 (CI -0.17 to +0.13, p=0.80, 172 blocks). Halves have opposite small signs. Only 4.7% (H1) / 3.5% (M30) of blocks show |z|>1.96 and mean z is ~-0.08: at this horizon gold behaves like a random walk block by block. The design rules out persistence above roughly rho 0.13 but cannot exclude small effects; one horizon (4h) and one block length (~10 days) tested. Not evidence against individual trend/breakout setups working via other mechanisms (that is Test 2). Conclusion: no basis for trend/mean-reversion regime confidence in Phase 4/5.

**Metric C v3 - persistence of the session-range regime exists for Asian only.**
- Asian (fixed UTC; unaffected by DST): significant and material at lookback 100 (+3.34% mean Brier gain, 6/6 combos) and lookback 150 (+2.83%, 4/6), but NOT at lookback 60 (+0.71%, 0/6). Moderately supported, lookback-sensitive - Metric C's own criterion was that a real effect holds across nearby lookbacks; it holds for 2 of 3.
- London: no effect in either session definition (gain -0.25% to +0.26%, 0 significant combos).
- NY: no effect under fixed UTC (one isolated '+' of 18, chance-level); under DST-aware sessions the transition model is significantly WORSE in several combos (-0.6% to -0.8%), i.e. estimation cost with no signal.
- The old claim "London/NY: real but conditional signal, only detectable with 3+ year windows" and its design implication (default to 3+ year windows for London/NY regime confidence) are WITHDRAWN.
- Consistent story (hypothesis, not proven): Asian-session volatility is smooth and persistent (also why trailing averages predicted Asian ranges so well in Metrics A/G), while London/NY volatility is spiky and event-driven, so yesterday's regime says little; intraday persistence (Metric I) is real because volatility clusters within a day.

**Updated status:** C - confirmed for Asian only (moderate), London/NY withdrawn; D - no evidence (replaced). Remaining provisional/unbuilt: E (descriptive), J (spread validation), K, L.

### Prerequisite added for Metrics K/L: DXY / gold timestamp alignment check (2026-09-21)
Script: `backtest\dxy_alignment_check.py` (auto-detects the DXY timestamp column; validated on synthetic feeds - detects a constant offset and a DST-shifting server-time offset of +120 min winter / +180 min summer). MT5 timestamps are usually broker server time, so the DXY minute feed may be hours off gold's UTC feed, or shift with DST. It runs a cross-correlation lag scan (overall, winter, summer) and an 08:30-New-York-release timing histogram for both feeds. **Do not build or run K/L until the peak lag is 0 in all seasons.** Result pending.

### DXY / gold alignment check - RESULT (added 2026-09-21)
Run on real data: **feeds are aligned.** Cross-correlation of 5-minute returns peaks (most negative, about -0.40 overall, -0.43 winter, -0.43 summer) at lag 0 in all three views, profile symmetric around 0. The 08:30 New York release timing check: gold and DXY both peak at 13:30 UTC (winter) and 12:30 UTC (summer), and both show the 10:00 ET secondary peak (15:00 / 14:00 UTC). No constant or DST-shifting offset. Column names confirmed: dxy_m1_ohlc(minute_ts, open, high, low, close), dxy_d1_ohlc(day, ...), bars_d1(bar_ts, ...).

**Coverage finding:** the gold minute table `minute_bars_ohlc` runs 2019-01-01 to **2025-12-31** (the DXY table runs to 2026-09-21). So every Test 1 metric built on it (all ~1,806 sessions) covers 2019-2025 only; **nothing in Test 1 tests 2026**, and K/L can only use the overlap 2021-07-19 to 2025-12-31 (~4.45 years). Opportunity: the 2026 Exness data could serve as a genuinely unseen holdout for the final confirmation of the key conclusions (different feed, so treat the comparison carefully).

Metrics K and L: script written and validated on synthetic data (detects planted lead-lag and planted persistent correlation regimes; clean on a constant-correlation null): `backtest\dxy_metrics_kl.py`. Results pending.

### Results: Metrics L and K on real data (added 2026-09-21; window 2021-07-19 to 2025-12-31, 4.45 years)
**Metric L (lead-lag) - no exploitable lead-lag; the relationship is contemporaneous.** 1-minute return correlation gold vs DXY: rho(0) = -0.379 overall, **-0.658 in the 08:25-08:45 New York release window**, -0.354 outside it. Every lagged correlation is ~0 (|rho| <= 0.011). The only statistically detectable asymmetry is at 1 minute (rho(+1) -0.011 vs rho(-1) -0.005; asymmetry -0.006, 95% CI -0.011 to -0.0015, "gold leads DXY"), which is economically nil (rho^2 ~ 0.0001) - plausibly DXY, a synthetic index computed from FX quotes, updating marginally later (inference). In the release window: no asymmetry (CI +/-0.03). Implication: DXY moves *with* gold, not before it, so it cannot be used as a leading indicator at retail latency; at releases it is a strong simultaneous read on whether a gold move is dollar-driven (a possible confirmation/filter feature to test in Test 2, not a predictor).

**Metric K (correlation-regime persistence) - regimes exist and persist strongly.** 101 non-overlapping 10-day blocks of hourly returns: per-block correlation mean -0.455, sd 0.207, 10th/90th percentile -0.69/-0.19, positive in only 2% of blocks. Sampling noise alone would give sd ~0.05: **94% of the between-block variance is beyond sampling noise.** Persistence: Spearman(rho_b, rho_b+1) = **+0.648** (95% CI +0.47 to +0.77, permutation p < 0.001). Per-year hourly-return correlation: 2021 -0.42 (H2 only), 2022 -0.48, 2023 -0.60, 2024 -0.41, **2025 -0.31** (weakest, consistent with reports of gold decoupling from the dollar - blog-level source only, not established here). 2026 is not covered (gold minute table ends 2025-12-31).

**Volatility-control check for K - RESOLVED: not a volatility artifact.** Controlling for gold volatility alone (the clean test - DXY volatility is partly an outcome of the coupling, so controlling for it can over-correct): persistence drops only from +0.648 to +0.606 (95% CI +0.42 to +0.73, p<0.001) - still strong. Volatility explains almost none of the block-to-block variation in correlation (R^2 = 0.03 for gold vol, 0.10 for DXY vol, 0.19 for both). Gold and DXY volatility are themselves persistent (+0.49 and +0.70) but that is not the source of the correlation persistence. **Conclusion: Metric K's finding stands as a genuine, separate phenomenon - confirmed, not provisional.**

**Phase 3 status after this round:** all 12 metrics now have a result on the corrected methodology - re-verified: A, I, C (Asian only), H (moderate), K, L (null lead-lag); null / no-evidence: B, D, F; withdrawn: G's positive claim; partly confirmed: J (needs spread validation); descriptive: E. **Open items:** J spread validation before touching SPIKE_TEMPLATE; 2026 holdout (Exness data); independent audit of scripts E/J; DST check for the remaining per-session scripts (B, E); apply a multiple-comparisons view across the ~12 metrics x sessions x combos.

### Demo-vs-live spread check: RESOLVED - data is trustworthy (added 2026-09-21)
Compared `tick_snapshot_demo_...` vs `tick_snapshot_real_...` for the exact Sept 4, 2026 NFP window on the user's own accounts (login 477135209 demo vs 296336401 live, both server Exness-MT5Real27/Trial9). Result: mean spread 0.2724 (demo) vs 0.2722 (live), correlation 1.000, ratio 1.00 at every minute including the 12:30 UTC release minute (0.26 -> 0.48 on both, identical). **Conclusion: for this account pairing, existing demo-sourced Exness tick data (`exness` and `exness_live` sources) is trustworthy for spread work** - no rebuild needed. Caveat: single event/day tested; a subtler divergence (e.g. only under extreme volatility) can't be ruled out from one comparison.

**Note found during account switching:** the `exness_live` source (70.9M ticks, confirmed **2026-01-01 to ~now**, 8.7+ months) sits entirely in the gap after `minute_bars_ohlc`'s 2025-12-31 cutoff - this is a genuine, untouched **2026 holdout** on a different (real tick, not Dukascopy) feed for later out-of-sample confirmation of the Test 1 conclusions. Not yet used.

**Source clarification:** `ticks.source` has 3 values - `dukascopy` (2019-2025, interbank reference, used for all price-structure metrics), `exness` (Sept 3-18 2026 only, the original one-off pull), `exness_live` (2026-01-01 to present, the main spread-modeling source going forward). The 2.000 max-spread value seen in both Exness sources is real, not a data-cleaning artifact - only 0.0003-0.0007% of ticks sit at that level.

### Metric J spread validation script (added 2026-09-21)
`backtest\spread_model_validation.py` - validates spread_model.py's SPIKE_TEMPLATE and FAMILY_SCALE_FACTOR directly against `exness_live` ticks (imports the real constants, not a copy). Two questions, kept separate: **Q1** - does the NFP spike shape (originally built from the single Sept 4 event) generalize across all NFP events in the 2026-01 to now window? **Q2** - does FAMILY_SCALE_FACTOR (derived from Metric J's PRICE-magnitude ratios) actually predict observed SPREAD widening at the peak offset, per family, with an "implied_scale" computed directly from spread data for comparison? Uses a per-event local baseline (median spread in the -30 to -3 min pre-event window, same day - avoids depending on normal_day_spread_profile.json), cluster (event-level) bootstrap CIs, and mirrors spread_model.py's own same-timestamp collision handling (max-scale family wins) so it tests actual production behavior. Validated end-to-end on synthetic data with a deliberately planted GDP scale mismatch (true 0.20 vs declared 0.41) - correctly recovered all true values within CI and correctly flagged the GDP mismatch (in_CI=False, implied_scale=0.20). Results on real data pending.

### Metric J spread validation - RESULTS and spread_model.py update (added 2026-09-21)
Full run on real data (`exness_live`, 2026-01 to 2026-09): 8 NFP, 9 CPI, 6 FOMC, 9 GDP, 1 PCE usable events after fixing the FOMC twin-release merge bug (Statement/Press Conference ~30 min apart were mutually excluding each other under the spacing filter before this fix).

**Q1 - the original template's peak (1.96x) was a genuine outlier, not typical.** Observed NFP peak across 8 events: 1.577x (95% CI 1.30-1.90) - the template's own value sits above the CI. Decay tail also runs longer than assumed: offsets 6-8 observed ~1.04-1.05x vs template's ~1.01x, CIs not overlapping. Worst-case (max) column: the Sept-4 event's own extreme tick (7.69x at offset 0) turned out to still be close to the worst actually observed across all 8 events (2.14-7.69x range) - i.e. Sept 4 was close to the worst case seen, just not the typical case.

**GDP/PCE finding:** diagnostics confirmed Core PCE Price Index (m/m and y/y) co-releases with GDP q/q at the same timestamp in ~89% of instances (matches the BEA's actual release schedule) - `nearest_event_group`'s own same-timestamp collision logic was already assigning these to whichever name has the larger scale factor (GDP, 0.41 > PCE's 0.34), so "GDP" events were mostly a blended GDP+PCE effect, and pure PCE occurred only once in this window (unusable, n=1).

**Q2 - corrected against the OBSERVED NFP peak (not the miscalibrated template value):** CPI implied scale 0.91 (declared 0.90 - confirmed), FOMC 0.74 (declared 0.69 - close), GDP(blended) 0.28 (declared 0.41 - meaningfully lower, but this is the GDP+PCE blend, not pure GDP), PCE unusable (n=1).

**Action taken:** `spread_model.py` updated (new file: `backtest/spread_model.py`, or replace in place) -
- `SPIKE_TEMPLATE` mean column replaced with the 8-event observed means; max column updated via a "never get less conservative" rule (max of old value and the worst single tick actually observed) - most max values unchanged, two offsets revised slightly upward. n=8 is still small for a worst-case figure; revisit periodically.
- `FAMILY_SCALE_FACTOR`: CPI 0.90->0.91, FOMC 0.69->0.74 (both confirmed/updated to measured values). GDP and PCE **merged into one family, "GDP_PCE" (scale 0.28)** - keeping them separate was misleading given the near-universal co-release; `RELEASE_FAMILY` now maps GDP q/q and both Core PCE Price Index names to "GDP_PCE". This also simplifies `nearest_event_group`'s tie-break for this specific collision (both names now resolve to the same family/scale regardless of which "wins"); the tie-break logic itself is kept for any other unforeseen collision.
- Verified with unit checks (not the live DB): template values, family unification, collision resolution, and the mean/worst_case scaling arithmetic all behave as intended.

**Status: Metric J is now fully confirmed, not partial.** This closes the last open item from Phase 3 flagged in the original external validation review. Remaining project-level open items: 2026 holdout validation (Exness data, unused so far), independent script audit for Metric E, and the still-provisional "worst-case" spread figure (small n, revisit later).

### Metric E rebuilt and corrected (added 2026-09-23)
Independent audit found the original `distribution_shape_stability.py`'s docstring was wrong about what it measures: it says "daily session returns" but the code computes `day_range / prior_close` - a strictly positive range statistic, not a signed return. Skew/kurtosis behave very differently for the two, so the earlier finding ("gold's tail behavior genuinely changes over time... Asian kurtosis swung from 0.192 to 52.515") cannot be read as a statement about return-distribution stability. It also had no significance test (every other Phase 3 metric got one after the 2026-09-21 review; this one was missed), fixed-UTC-only sessions, no event-day accounting, and no CSV output.

**Two corrected scripts, both with a shared block-permutation significance test** (`distribution_stability_common.py` - shuffles blocks of the pooled train+test data to ask whether a fold's skew/kurt diff exceeds what an arbitrary split of the same data would produce), DST-aware London/NY sessions, event-day flagging (does excluding NFP/CPI/FOMC/GDP/PCE days change the conclusion), and CSV output:
- `distribution_shape_stability_v2a.py` - corrected version of the ORIGINAL metric (the range-ratio), for anyone who wants that specific question re-answered properly.
- `return_distribution_stability.py` - the genuine signed-return version (log of session close/open) that the original docstring's name implies - this is the one to use for anything downstream that assumes a return-distribution shape (stop-loss/take-profit sizing, VaR-style risk assumptions in Phase 4/5).

**Real finding from validating the permutation test on synthetic data:** kurtosis needs a substantially bigger sample or a bigger true effect than skew to reach significance - confirmed by direct simulation, not just asserted. This directly explains why the old kurtosis swing was untrustworthy, and means: **trust a skew-based finding at much smaller n than a kurtosis-based one** in every result these two scripts produce. Both scripts flag folds with fewer than 60 observations per side as "low-n" for kurtosis specifically.

**Testing:** both scripts run end-to-end on synthetic minute-bar data (correct fold/session mechanics, correct CSV output); the block-permutation core was separately validated against known synthetic distributions (correctly stayed non-significant on two identical-distribution samples, correctly flagged a real sustained shape shift, correctly showed low power on a sparse-outlier contamination case - itself informative about the method's limits). The `ATTACH ... TYPE sqlite` event-day lookup could not be tested in this sandbox (no internet access to fetch DuckDB's sqlite extension) but uses the exact same pattern already working in `catalyst_magnitude_prediction.py` and `anomaly_flagging_v2.py`.

Results on real data pending for both scripts.

### Metric E results on real data (added 2026-09-23)
~175 folds tested per session/mode across both scripts (~340 total individual tests). Reading rule applied: with this many folds at alpha=0.05, a handful of scattered, marginal (p~0.02-0.05) hits are expected purely by multiple-testing noise - most of the "sig=" flags in the raw output fit that pattern (isolated, inconsistent across overlapping combos testing the same period, several flip to non-significant when event days are excluded) and should NOT be treated as individual findings.

**One result is not noise and is the real finding of this metric: Asian session, H2 2023.** Confirmed in BOTH scripts (range-ratio v2a and signed-return v2b), in BOTH window schemes covering that period (expanding_test6mo, rolling_3yr_test6mo), with p=0.000 for skew AND kurtosis every time (0/1000 permutations matched or exceeded the observed diff) - and it does NOT flip when event days are excluded, so it is a sustained shape change, not a 1-2 day calendar-release artifact. Grounded cause (web search, 2026-09-23): gold entered a historic rally starting Oct 2023 on the Israel-Gaza conflict's onset, rallying from <$1820 to a new all-time high >$2070 by early Dec, with a $120 intraday range and a sharp overnight move Dec 3-4 - a genuine, identifiable geopolitical shock, not a data artifact.

**Revised Metric E conclusion:** not "gold's distribution shape is generally unstable" (most periods show no detectable shift) but "gold's distribution shape can shift sharply and durably around major geopolitical shocks, and this corrected script can detect it." Design implication for Phase 4/5: a regime/shock-detection layer that can flag "possibly in a structurally different distribution right now" is worth building, rather than assuming setups trained on calmer periods generalize through events like Oct-Dec 2023.

**Secondary notes:** several folds' significance depends on whether event days are included (flagged via the "NOTE: excluding event days..." lines) - read these as event-day-driven, not persistent shifts. DST-aware London/NY sessions showed slightly more scattered significant folds than fixed-UTC in both scripts, but the difference is small and not clearly more than noise-level variation between two different samples of the same underlying days.

**Status: Metric E is now genuinely confirmed** (previously "descriptive, unaudited"). This closes the independent-script-audit open item. Remaining project-level open items: the 2026 holdout (exness_live data, unused so far) and the worst-case spread figure in spread_model.py (revisit as more NFP events accumulate).

### 2026 holdout results: Metrics A and I (added 2026-09-23)
Genuine train(2019-2025)/test(2026) holdout via `build_2026_holdout_bars.py` (OHLC bars built from `exness_live` ticks into a separate `analytics_2026_holdout.duckdb`, mid-price assumption flagged) and `holdout_2026_evaluate.py` (single train/test split, not the 6-combo matrix - see script docstring for why the matrix doesn't apply to an 8.7-month holdout).

**Context (web search, 2026-09-23):** gold crossed $4,000 for the first time in Oct 2025, hit an all-time high near **$5,590 on Jan 28, 2026** (its first inflation-adjusted record, beating 1980), then traded in the $4,500-5,190 range with reporting noting "$100-200 single-session swings have become routine." Drivers: record central-bank buying (700+ tonnes in 2025, most since 1967), a weak dollar, geopolitical tension. The 2026 test window's mean price was ~$4,560 - roughly double the 2019-2025 average.

**Metric A holdout - qualitative fix holds, quantitative accuracy genuinely degrades.** %-of-price MAE (the fair comparison across very different price regimes) still ranks trail5_pct < trail20_pct < pct_train in every session - the trailing-average fix from the original re-test generalizes to genuinely new data. But Asian's relative error (0.71-0.89%) is roughly 2-3x its 2019-2025 level (~0.25-0.4%), and the pct_train-vs-trail20_pct significance test remains significant for Asian specifically (p=0.028), same direction as before. London/NY show no significant difference at n=184 (underpowered on a single year, not a contradiction of the original finding). **Coverage badly fails everywhere:** Asian 80%/90% intervals covered only 39%/62% of actual outcomes (vs the 80%/90% they're calibrated to); London ~63%/64% and 76-79%; NY ~61-62%/74-76%. This is a scale-invariant, genuine finding: 2019-2025-calibrated interval widths do not hold up in 2026's historically volatile regime.

**Metric I holdout - confirmed and stronger than in-sample, with proper CIs.** All 4 timeframes significant: D1 +2.64% [+0.48,+4.93] (newly established - never confidently significant in-sample), H4 +5.86% [+2.09,+10.67], H1 +7.58% [+3.72,+12.58], M30 +8.89% [+4.68,+14.70] - every one exceeds its 2019-2025 in-sample estimate.

**Design implication (added to gold-ea-ai-decision-layer.md):** the metrics that survived the holdout well were already adaptive (Metric A's trailing-window model, Metric I's rolling time-of-day-relative regimes); the one that failed was a fixed historical calibration (Metric A's interval quantiles). Working hypothesis, not proven: a market producing large sustained directional swings (as 2026 did) may make volatility clustering itself more pronounced, which would explain why persistence (Metric I) got stronger in the same period where a fixed calibration (Metric A's intervals) broke down. **Recommendation for Phase 4/5: any interval or threshold calibrated on a fixed historical window should be treated as provisional and revisited/made adaptive, not assumed stable - this is now a demonstrated failure mode, not just a theoretical concern.**

**Status:** A and I holdout-confirmed. C, H, K, L holdout evaluation still pending (same design needed: single train/test split, not the 6-combo matrix, with rolling windows seeded across the 2019-2025/2026 boundary).

### 2026 holdout results: Metrics C and H (added 2026-09-24)
Same design as A/I: single train(2019-2025)/test(2026) split via `holdout_2026_ch.py`, rolling windows seeded across the boundary.

**Metric H - robustly confirmed, stronger on new data for the opening-range flag.** 7/10 open-flag tests significant on a single ~8.7-month window (Asian vs full 3.84x, vs rest 3.52x; London dst vs full/rest 2.73x/2.67x; NY fixed vs full/rest 2.58x/2.27x; London fixed vs full 2.22x; NY dst vs full 2.08x) - every lift exceeds its 2019-2025 in-sample value. Calendar-flag: same direction everywhere (lift 1.47-1.91x, all >1x) but none reach significance - read as a sample-size artifact (a single year has far fewer NFP/CPI/FOMC/GDP days than the multi-year pooled sample the original result used), not the effect disappearing.

**Metric C - Asian's known effect holds and strengthens; one new candidate finding at London.** Asian lookback=150: +8.13% [+1.25,+16.02], significant (stronger than original +2.83%); lookback=100 similar point estimate to before (+3.81% vs +3.34%) but CI now crosses zero (n=185 single-year test, lower power than the original pooled multi-fold estimate - not a contradiction). **New: London lookback=60 is significant in BOTH session definitions** (fixed +1.71% [+0.67,+2.83], dst-aware +1.38% [+0.23,+2.57]) - London showed NO effect at any lookback in the original 2019-2025 study. Replication across both session definitions is real partial confirmation, not a fluke of one arbitrary choice, but this is one year of data finding something 5+ years didn't - treat as a candidate/hypothesis to watch, not an established effect. Multiple-testing context: 15 tests in this metric's holdout batch, ~0.75 false positives expected by chance at alpha=0.05; got 2 distinct signals (Asian continuing, London new) - above the noise floor but not overwhelming. NY: no significant results, consistent with the original null.

**Possible unifying explanation (hypothesis, not proven):** 2026's historically volatile, strongly trending market (see market-context note above) may make regime persistence detectable in sessions/lookbacks where calmer markets don't show it - would explain both the new London C finding and why Metric I's holdout gains came back stronger everywhere rather than weaker. Worth testing against more 2026+ data as it accumulates, not something to design around yet from one year.

**Status:** A, C, H, I holdout-confirmed (C/London flagged as a new candidate needing more data). K, L holdout evaluation still pending.
