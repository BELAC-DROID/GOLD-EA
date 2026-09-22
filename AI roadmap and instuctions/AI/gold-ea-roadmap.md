# XAU/USD Gold EA — Build Roadmap & Progress

*Last updated: 2026-09-21 (Metrics A and B re-tested against a shared 6-combo walk-forward matrix; Metric J (catalyst magnitude) built and completed — Phase 3 now at 10/12; recovered from another session-fork gap where this work wasn't synced to tracking files before the session ended)*

This tracks the **infrastructure + baseline-profiler + Test 1 build track** as the single place that stays current across sessions.

**Agreed build order:** Infrastructure → Baseline Profiler → Test 1 (calibration check) → 10 Setups → AI Decision Layer, with Risk Controls built in parallel throughout.

---

## Phase 1: Infrastructure — ✅ Functionally complete

All prior items still stand (Windows VM, MT5/Python connection, timezone clean, Dukascopy 6-year load, spread model, calendar). Additions this update:

### Data quality — bug found and fixed
- **`audit_ticks.py` on `dukascopy`:** clean — 0 duplicate timestamps; "thin days" all land on 7-day intervals from a Sunday (expected weekend partial-session pattern, not a defect); the D1-count-vs-weekday-count mismatch is explained the same way.
- **`audit_ticks.py` on `exness_live`: caught a real bug.** All rows collapsed to `1970-01-21` and 9,056,422 "duplicate" timestamps were found. Root cause, confirmed by direct calculation: `timestamp_utc_ms` was actually being stored in **seconds**, not milliseconds — a pandas datetime-resolution inference issue in the loader (`.astype("int64")` on the parsed datetime returned a coarser resolution than assumed, so the `// 1_000_000` conversion produced seconds, not ms). This also fully explains the duplicate count: distinct millisecond-level ticks were collapsing onto the same integer-second value.
- **Fixed and reloaded, now independently reconfirmed in this thread.** Rerunning `audit_ticks.py exness_live` after the fix:
  - Date range: `2026-01-01` to `2026-09-18` — correct (was `1970-01-21` before the fix)
  - Duplicate timestamps: `1,024,603` (down from `9,056,422`) — ~1.44% of rows. **Spot-checked and confirmed genuine:** sample timestamp `1769014746296` holds two distinct bid/ask pairs (`4836.361/4836.521` vs `4836.331/4836.491`) — legitimate same-millisecond quote updates, not a defect.
  - Thin-day pattern: correctly lands on Sundays and the Jan 1 holiday — expected, not a defect.
- **✅ Fix fully confirmed — no open items remaining on the Exness reload.**

### 🔲 Not yet done
- [ ] Validate the spread spike template against a second real event type (CPI/FOMC/PCE)
- [ ] Confirm MT5 custom-symbol import for in-terminal backtesting
- [ ] Spot-check a sample Exness duplicate timestamp to confirm genuine differing bid/ask (see above)

---

## Phase 2: Baseline Profiler — ✅ Complete and fully verified

All three pieces (session range, level-reaction, volatility rhythm) are now confirmed trusted.

### Session range profile: ✅ trusted (unchanged from before)

### Volatility rhythm profile: ✅ fully verified and trusted
Bug fixed earlier (`floor()` instead of a rounding cast). Independently spot-checked this session via three checks: the `"21:00"` bucket is correctly absent (fully inside the closure); the partial `"20:45"` bucket (13 clean minutes, since the closure starts mid-bucket at minute 1258) shows a sane, proportionally lower range than a full 15-minute window; and two independently-recomputed closure-free buckets (`03:00`, `10:00`) matched the grouped profile's numbers exactly. No open items remaining.

### `level_reaction.py` → `level_reaction_v2.py`: ✅ trusted; refactored into a shared module
The original 5-round-debugged version (4,945 touches) used a **fixed $10 level spacing**, which breaks down as gold's price moved from ~$1,300–2,600 (2019–2024) to $3,000–3,700+ (2025). Rebuilt with **price-relative tiering**. Major ($50)/minor ($10) stratification found to add no real distinguishing value — dropped from the final report.

**Confirmed and trusted — final tiered result:**
```json
tier1_under_3000 (spacing=$10/50): 5,372 touches, 1,931 days, 2.78/day
  reject 32.1% (1,725)  break 29.0% (1,560)  consolidate 38.8% (2,087)
tier2_3000_and_above (spacing=$25/100): 656 touches, 249 days, 2.63/day
  reject 31.2% (205)  break 28.5% (187)  consolidate 40.2% (264)
```
Touches/day is comparable across tiers (2.78 vs 2.63), confirming the tiering fix worked — under the old fixed-$10 scheme, tier2 would have shown inflated frequency.

Logic was then extracted into `models\level_reaction_core.py`, imported by both this script and the Phase 3 walk-forward script (see below), so they can't drift apart the way the walk-forward script originally did. Refactor verified to reproduce identical numbers to the above before trusting anything built on top of it.

### Next for Phase 2
- (none — Phase 2 is complete)


---

## Phase 3: Test 1 — Understanding — 🔄 In progress, 10 of 12 metrics done

### Shared walk-forward window matrix — built, applied retroactively to Metrics A and B
A pre-committed matrix of 6 window schemes (`expanding_test1yr`, `expanding_test6mo`, `rolling_2yr_test1yr`, `rolling_3yr_test1yr`, `rolling_4yr_test1yr`, `rolling_3yr_test6mo`), stepping forward through the full 2019–2026 dataset to generate multiple pooled folds per combo rather than 3 fixed anchor splits. Committed *before* seeing any results, specifically to avoid reintroducing look-ahead bias by picking whichever window scheme happens to perform best after the fact. Built as `backtest/walk_forward_matrix.py`, a shared split generator imported by every metric that needs walk-forward testing — new metrics should use this rather than inventing their own splits.

### Metric C: Volatility regime classification — ✅ done, robustly tested
Regime label (low/normal/high) via rolling percentile rank (20th/80th), recomputed continuously through the dataset — deliberately avoids the fixed-boundary trap found elsewhere this session. Scored as a regime-transition model (P(today's regime | yesterday's regime)) vs. naive majority-class only — a naive "persistence" baseline (today=yesterday) was tried first but dropped: it made a hard, 100%-confident guess compared against soft probability models under Brier scoring, which structurally guarantees the soft model wins regardless of real information content, not a fair comparison.

**Tested across 18 configs (3 lookbacks: 60/100/150 days × 6 window combos):**
- **Asian: beats majority in 18/18 configs, no exceptions.** Confirmed robust — real, usable volatility clustering.
- **London/NY: a real but conditional signal.** Beats majority consistently only in the `rolling_3yr` and `rolling_4yr` combos, at every lookback length — never in `expanding` or `rolling_2yr`. Longer training windows (3+ years) are needed to detect the signal; shorter/expanding windows dilute it into noise.

**Design implication for Phase 4/5:** the AI decision layer should default to a 3+ year training window specifically for London/NY volatility-regime confidence — an expanding or short-rolling window would miss a real signal that's there.


### Metric B: Level-reaction walk-forward — ✅ done, with a precise, non-obvious finding
`test1_level_reaction_walkforward.py` was found still using the pre-tiering flat $10 spacing (a third instance of the same fixed-dollar-assumption bug) — rebuilt on the shared `level_reaction_core.py` tiering logic, stratifying by **tier** (not major/minor, consistent with that split adding no value).

**Result:** the tier-stratified model never beat the pooled-soft (no-tier-split) baseline across any of the 3 splits — Split 1/2 showed exact equality, Split 3 showed the model losing.

**Robustness check — pre-committed 6-combo window matrix (expanding 1yr/6mo test; rolling 2/3/4yr train × 1yr/6mo test), applied to both metrics, per the research-backed critique that a single window choice risks being an artifact rather than a real result:**

**Range prediction:** London and NY beat naive across **all 6 combos** — robust, trustworthy. Asian session beats naive in 4/6 combos but **loses to naive specifically in `rolling_3yr_test1yr` and `rolling_4yr_test1yr`** — longer rolling training windows consistently hurt Asian, shorter/expanding windows don't. **Revised, more precise conclusion:** trust the percentage model for London/NY; treat Asian as genuinely unproven, not just "mildly weaker," until this pattern is understood further.

**Level-reaction tiering:** model **never** beats pooled-soft in any of the 6 combos (consistent ~0.001–0.002 Brier gap every time, not just in the one earlier split). Strongly confirms — not just single-split-suggests — that tiering hasn't demonstrated predictive value, still attributed to tier1 (5,372 touches) vastly outnumbering tier2 (656) in the pooled data. Keep tiering for touch-detection correctness; don't use it for confidence scoring yet.

### Metric A: Range prediction — rebuilt from fixed-dollar to percentage-of-price
The original walk-forward test used a fixed mean-dollar-range prediction learned from the training period — this failed badly on Split 3 (2025 test period) for the same root reason as the level-spacing bug: a fixed dollar figure learned at 2019–2024 prices doesn't transfer to 2025's much higher price level.

**Fix (`test1_range_prediction_v2.py`):** predict range as a **percentage of prior close** (not same-day price, to avoid lookahead — yesterday's closing price is genuinely known before the test day starts), learned from the training period's ratio, applied to each test day's own prior close.

**Full walk-forward result:**

| Split | Test period | Session | Old fixed-$ MAE | New %-model MAE (95% CI) | Naive MAE | Verdict |
|---|---|---|---|---|---|---|
| 1 | 2023 | asian | 3.627 | 4.275 (3.84–4.81) | 4.246 | worse than naive, worse than old model |
| 1 | 2023 | london | 6.407 | 6.871 (6.20–7.56) | 8.384 | beats naive, worse than old model |
| 1 | 2023 | ny | 6.598 | 6.892 (6.27–7.55) | 8.298 | beats naive, worse than old model |
| 2 | 2024 | asian | 6.464 | 5.307 (4.63–6.06) | 6.334 | beats naive, beats old model |
| 2 | 2024 | london | 8.760 | 7.874 (6.96–8.85) | 10.714 | beats naive, beats old model |
| 2 | 2024 | ny | 9.140 | 8.331 (7.39–9.34) | 10.618 | beats naive, beats old model |
| 3 | 2025→now | asian | 22.179 | 15.040 (13.07–17.19) | 13.789 | worse than naive, **beats old model by ~32%** |
| 3 | 2025→now | london | 21.151 | 13.728 (11.56–16.10) | 17.049 | beats naive, **beats old model by ~35%** |
| 3 | 2025→now | ny | 21.214 | 13.999 (12.11–16.20) | 16.437 | beats naive, **beats old model by ~34%** |

**Honest read, not just the win:** Split 3 (the case that mattered most, since it's the regime the setups will actually trade in) improved dramatically — ~30–35% error reduction across all sessions. But Split 1 showed the percentage model losing to the old fixed-dollar model, especially in `asian`. This is a genuine bias-variance tradeoff, not a bug: fixed-dollar is low-variance but systematically wrong once price has moved; percentage-of-price rescales correctly for regime shift but adds day-to-day noise when the test period's price is comparatively range-bound.

**Confirmed and sharpened by the 6-combo window matrix (see below):** this isn't just a Split-1 quirk — Asian session genuinely, structurally underperforms naive under longer rolling training windows specifically, while London/NY are robust across every combo tested. **Revised verdict:** trust the percentage model for London and NY; treat Asian as unproven, not just weaker, pending further investigation.

**Possible future refinement (not urgent):** a blended model weighting percentage vs. fixed-dollar based on how far the test period's price has drifted from the training average — flagged as an option, not built, pending whether the Split-1-style tradeoff actually matters once Phase 4 setups exist.

---

### Metric D: Hurst / trend-mean-reversion character — ✅ done, with a caught-and-fixed measurement artifact
First version tested **day-to-day** regime transitions using a 60-day overlapping Hurst window — looked dramatic (6/6 combos beat majority, margins like 0.21 vs 0.52), but a stickiness check revealed why: 87.4% of consecutive labels were mechanically identical, since 59/60 days of underlying return data overlap between one day's window and the next. The "beats majority" result was mostly re-discovering window overlap, not real trend-character persistence.

**Fix:** test transitions **20 days apart** instead of 1, so compared windows share far less overlapping data. Re-ran the stickiness check at the new stride: 57.6% unchanged vs. a calculated 47.3% chance baseline (from the regime distribution's base rates) — a real ~10-point excess, but the two windows still share two-thirds of their data at this stride, so the effect is likely still somewhat inflated by residual overlap, not a fully clean measurement.

**Final result:** 17/18 combos beat majority (NY's `rolling_2yr_test1yr` is a genuine exception, not hidden). **Verdict:** trend/mean-reversion character shows real but modest persistence — usable, but should carry less confidence weight than Metric C's Asian result, which had no overlap concern to begin with.

### Metric F: Weekend gap behavior — ✅ done, clean negative result
No overlapping-window concern (discrete weekly events). **0/6 combos beat majority** — naive majority wins every time. **Weekend gap size shows no week-to-week persistence** — a trustworthy negative finding, not a bug or a thin-sample artifact.

### Metric E: Distribution shape stability — ✅ done, a genuinely important descriptive finding
No naive baseline by design — descriptive, not scored pass/fail. Train-period skew/kurtosis are consistently very high (expected — range is a bounded, fat-tailed statistic), but **test-period values are highly unstable across folds**: Asian's test kurtosis ranges from `0.192` to `52.515` depending on which 6-month fold, a ~270x spread from the same instrument. This is a genuine finding about gold's tail behavior changing character over time, not noise.

**Clear, consistent session ordering across nearly every window scheme:**
- **NY: most stable** (best case `rolling_2yr_test1yr`: |skew diff|=0.449, |kurt diff|=3.327)
- **Asian: least stable** (worst case `expanding_test6mo`: |skew diff|=1.471, |kurt diff|=13.693)
- **London: in between**

**Implication for Phase 4/5:** position-sizing/risk logic (Section 8) assuming stable tail risk should apply that assumption with the least confidence to Asian-session trades and the most to NY-session trades — session-dependent caution, not a uniform risk treatment.

### Metric G: Session-open prediction — ✅ done, clean, with a notable cross-metric pattern
Fixed the f-string bug (`{OPEN_WINDOW_MINUTES * 0.5}`), reran clean. **London/NY beat naive in all 6 combos** — robust. **Asian beats naive in 5/6**, losing only in `rolling_4yr_test1yr` (razor-thin margin: 2.5222 vs 2.5029).

**Cross-metric pattern worth naming explicitly:** this is the same session and the same long-rolling-window territory where Metric A's percentage-based range model also broke down (Metric A lost in Asian's `rolling_3yr_test1yr` *and* `rolling_4yr_test1yr`). Two independent metrics now point at the same structural weakness: **percentage-of-price models for the Asian session specifically degrade under longer rolling training windows.** Worth actively checking for this in any future Asian-session percentage-based metric, not re-discovering it separately each time.

### Metric H: Anomaly-flagging precision — ✅ done, both halves, robust
**Volatility-spike half:** flags a day when its opening 30-min range exceeds the 90th percentile of a trailing window; ground truth is the same session's full-day "high" regime label from Metric C. **Beats base rate in all 18 tests** (3 sessions × 6 combos). Asian shows the strongest lift (~3x: precision 0.61–0.69 vs. ~0.22–0.24 base) — notably, Asian is the *strongest* performer here, not the weak link seen in Metrics A/G, confirming that pattern is specific to percentage-of-price/long-rolling-window models, not Asian sessions generally.

**Calendar-proximity half:** flags a day when a `spread_model.py`-whitelisted high-impact event (imported directly, not duplicated) falls inside that session's UTC window. **Asian correctly shows 0 event-days** — all whitelisted events are US releases (NFP, CPI, FOMC, GDP) whose UTC times never fall in the 00:00–08:00 window; this is the expected, correct result, not a bug. **London (358 event-days): ~1.7x lift, robust across all 6 combos. NY (178 event-days): ~2.2x lift, the strongest of the two sessions, also robust.**

### Metric I: Cross-timeframe consistency — ✅ done, extended to all 4 available timeframes
Design doc named H1/H4; extended to include M30 and D1 too (already-built tables, no extra cost, and a more complete generalization claim than just two arbitrarily-named timeframes). M15 excluded as circular — Metric C was built from M15-derived data.

**Result — a clean, monotonic timescale gradient:**
```
D1:  6/6 beats majority (robust)
H4:  6/6 beats majority (robust)
M30: 4/6 beats majority (mixed)
H1:  1/6 beats majority (essentially no signal — model≈majority to the 4th decimal)
```
Volatility clustering weakens steadily as granularity gets finer and essentially vanishes at H1 — consistent across all 6 window combos at every timeframe, not a one-off. D1's small total bar count (2,171) raised a legitimate thinness concern beforehand, but resolved cleanly — n_test values were proportionally healthy, no issue.

**Design implication for Phase 4/5:** build volatility-clustering confidence signals at D1/H4 granularity only. Hourly-resolution (H1) regime confidence would not be supported by real signal per this data — using it would manufacture false confidence from noise.

### Metric J: Catalyst magnitude prediction — ✅ done, closes a real Phase 1 debt item
Tests whether `spread_model.py`'s `SPIKE_TEMPLATE` (calibrated on exactly one NFP event, applied uniformly to all 11 whitelisted event types since Phase 1) is actually a reasonable stand-in for every event type — flagged as unvalidated back in Phase 1 and never revisited until now.

**3 rounds of dedup bugs, root-caused via staged diagnostic before trusting any result:**
1. v1 didn't dedup calendar events sharing an exact release timestamp at all — CPI/PCE/FOMC families routinely publish several named sub-metrics simultaneously (979 raw rows, only 494 distinct timestamps) → inflated to 2,595 rows once joined to price data.
2. v2 deduped *after* the price joins — by then the duplicate timestamps had already fanned out combinatorially in the join (2 dupes × 2 dupes = 4 rows, not 2) → still wrong (426, should be ≤494).
3. v3 fixed it by deduplicating the events table *before* any price join — the correct approach. Interestingly, v2 and v3's final numbers matched byte-for-byte anyway, since the duplicate rows all carried identical real price values; post-hoc dedup accidentally landed on the same answer as pre-hoc dedup. Confirmed via two independent code paths reaching the same number, not just assumed correct.

**One other correction worth naming:** the original plan was to validate against `spread_model.py`'s reported "979 events" figure — that was the wrong target. 979 is Phase 1's intentionally-undeduplicated raw count (fine for its own nearest-event-lookup use case); the correct deduplicated release-moment count is 494.

**Final result: 426 usable events** (±2min pre / +8min post-release price moves), grouped by release family (NFP/CPI/FOMC/GDP/PCE).

**Part 1 — does NFP's magnitude generalize to the other event types?** No — confirmed with **p<0.0001** (Welch's t-test, NFP vs. all others pooled). Magnitude ordering: NFP (mean 0.365% of price) > CPI (0.328%) > FOMC (0.253%) > GDP (0.150%) ≈ PCE (0.124%). GDP and PCE move gold less than half as much as NFP; CPI is the closest match; FOMC is moderately overstated by the current uniform template.

**Part 2 — does knowing the release family actually improve prediction, or is this just "NFP is different" trivia?** Tested against the same 6-combo window matrix: **per-family average magnitude beats pooled naive in all 6 combos**, consistent ~5–10% MAE reduction. This is the evidence needed to justify actually changing `spread_model.py`, not just a descriptive curiosity.

**Concrete recommendation, not yet implemented:** split `SPIKE_TEMPLATE` by release family — keep NFP/CPI/FOMC near full strength, scale GDP/PCE to roughly half strength, rather than applying one NFP-derived shape uniformly across all 11 whitelisted event types.

## Phase 4: The 10 Setups — ⬜ Not started


## Phase 5: AI Decision Layer — ⬜ Not started
## Risk Controls — ⬜ Not started (build in parallel with Phase 4, not after)

---

## Open risks carried forward
- **Session fork risk — actively demonstrated this round:** the Exness timestamp fix, the level-reaction price-tiering fix, and the range-prediction percentage fix all happened in a session that then got cut off mid-update, before its own tracking-file sync completed. This document is the recovery/consolidation of that work — a reminder that the fork risk isn't just theoretical.
- **A general pattern worth naming explicitly:** two separate bugs this round (level spacing, range prediction) had the *same root cause* — a fixed-dollar assumption breaking as gold's price level shifted. Worth checking whether any other planned metric (e.g. catalyst magnitude, distribution shape) has a similar implicit fixed-dollar assumption baked in before building it, rather than discovering it the same way a third time.
- **Compute sizing, spread-transfer assumption:** unchanged from before.

## Immediate next steps (in order)
1. Implement Metric J's recommendation in `spread_model.py` — split `SPIKE_TEMPLATE` by release family (NFP/CPI/FOMC full strength, GDP/PCE ~half strength) instead of one uniform NFP-derived shape.
2. Source DXY historical data as a single dedicated task, then build correlation-regime tracking + lead-lag alignment together (Metrics K/L, the last 2 of 12) — Phase 3 will be complete after these two.
3. When Phase 4/5 design starts, apply: 3+ year training window for London/NY volatility-regime confidence (Metric C); weight Metric D's persistence signal lower than Metric C's, given the residual-overlap caveat; treat weekend gap size as non-predictive (Metric F); apply session-dependent tail-risk caution per Metric E (least confidence in Asian, most in NY); avoid long rolling windows for Asian-session percentage-based models (Metrics A, G); anomaly-flagging (Metric H) is a genuinely strong, robust confidence signal across all sessions; build volatility-clustering confidence at D1/H4 granularity only, never H1 (Metric I); use per-release-family magnitude, not a uniform NFP-derived shape, for catalyst-driven position sizing (Metric J).
