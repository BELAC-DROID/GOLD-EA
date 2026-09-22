# Gold (XAUUSD) Multi-Setup EA + AI Decision Layer — Design Notes

*Living document — updated as the project evolves.*

*Revised 2026-09-21: added Section 7.4 (Test 1 revisions from external validation review) and inline flags in 5.6 and 9.3. Original text otherwise unchanged.*

---

## 1. Infrastructure

### Hosting: Oracle Cloud, UK region
- MT5 is Windows-only, so two paths on Oracle Cloud:
  - **Windows VM**: install MT5 natively. Oracle's free tier doesn't include a free Windows image (only Linux free-tier shapes are free) — a Windows instance is paid, but usually still cheap vs a third-party VPS.
  - **Linux VM + Wine**: use an Always-Free Linux shape (Ampere ARM or AMD micro instance) and run MT5 via Wine. Works for most EAs; can be finicky with heavy chart objects/custom indicators or DLL-dependent EAs.
- Oracle's free-tier compute can occasionally be reclaimed/throttled depending on region demand — worth checking current availability or budgeting for a paid shape if reliability matters.

### Broker: Exness
- Exness runs core trading servers across multiple hubs — notably **London** and **Amsterdam**, plus New York, Singapore, Hong Kong, Tokyo.
- A UK-region Oracle VM should give very low latency to Exness (single-digit ms range from London-based tests).
- To confirm: in MT5, **Tools → Options → Server** shows which Exness server the account connects to. Use MT5's built-in ping test to confirm actual round-trip time once the VM is live.

### Windows trial option
- **Windows Server Evaluation edition** offers a free ~180-day trial, fully functional (not crippled).
- Catches:
  - After 180 days it begins shutting down periodically (hourly) until activated or reinstalled — risky for a live, unattended EA.
  - Oracle Cloud typically offers licensed Windows Server marketplace images (billed hourly), not the bare evaluation ISO — running the evaluation specifically usually means bringing a custom image, which is more setup work and less officially supported.
  - This trial applies to Windows *Server* editions, not desktop Windows 10/11 — fine, since MT5 runs well on Server editions.
- **Recommendation given this is for live trading on a small account:** avoid the trial route (forced restarts mid-trade are a real risk). Either use the Linux + Wine route (free, never expires) or a standard licensed Windows Server image (paid but stable, nothing to renew).

---

## 2. Project Direction: 10 Setups + AI Decision Layer

**Scope note:** the account will eventually trade 5 forex pairs in total, but this entire design (10 setups, AI decision layer, RR system, confidence/catalyst modeling) is being built and proven on **XAUUSD first**. Multi-pair expansion is deferred — when it happens, the schema should carry a `symbol` field throughout, and edge/confidence should be computed per-pair rather than pooled, since a setup's edge on gold won't necessarily transfer to another pair.

 Run ~10 different trading setups, all on XAUUSD, each acting purely as a *signal detector* — finding and flagging potential positions. An AI layer sits on top as the final trade-decision expert, evaluating each setup's historical edge before any trade is actually taken.

The AI's job, as specified:
- Check past performance of how much each setup had an edge
- Identify **when** they had the edge
- Identify **why** they had that edge
- Find the **recurring patterns** when an edge occurs
- Quantify **how much the candle rose or fell** when the edge occurred (magnitude of the move)
- Plus additional ideas below

### 2.1 Separate "detection" from "decision"
- Each of the 10 setups only **logs a signal record** when it fires — none of them trade directly.
- Log per occurrence:
  - Setup ID
  - Timestamp
  - Session (Asian / London / NY / overlap)
  - Direction
  - HTF trend state
  - ATR / volatility regime
  - Spread at the time
  - Distance to key levels (daily high/low, round numbers)
  - Proximity to high-impact news (NFP, FOMC, CPI)

### 2.2 Track outcomes, not just entries
For every signal, log forward what actually happened:
- MFE / MAE over the next N candles
- R-multiple achieved
- Time-to-target
- Raw candle move size (in pips **and** ATR-normalized) at 1, 3, 5, 10 candles out — this is what lets the AI later state "this setup's edge shows up as a 15–25 pip push within 3 candles."

### 2.3 Compute *conditional* edge, not overall edge
Overall win rate per setup is close to useless. Slice edge by:
- Session
- Volatility regime
- Trending vs ranging
- Day of week
- Confluence (2+ setups firing simultaneously)
- Recent streak / hot-vs-decaying state

This slicing is where "why" and "recurring pattern" answers actually come from — the AI's core job is pattern-mining across these slices.

---

## 3. Additional Factors for the AI to Weigh

### Market microstructure context
- **Liquidity sweep / stop-hunt detection** — did price take out a recent high/low right before the setup fired? Many gold setups only have edge *after* a liquidity grab, not on a clean break.
- **Order flow proxy** — tick volume spikes, unusual candle range vs average (a signal on a 3x-ATR candle behaves very differently than on a quiet one).
- **Spread/slippage conditions at signal time** — a setup can look great in backtest but bleed edge live if it systematically fires when spreads are already wide.

### Timing granularity beyond session
- **Minutes since session open** — first 15 minutes of London/NY open behaves differently than mid-session.
- **Proximity to rollover** (already filtered in the base EA) and to weekly/monthly candle open/close — gold often shows open-specific behavior.
- **Day-of-month effects** — options expiry, month-end rebalancing flows are real for gold.

### Setup interaction, not just confluence
- **Sequence, not just simultaneity** — does setup A firing 10 candles before setup B increase B's win rate? Order matters, not just "did they agree."
- **Conflict resolution** — explicit rule for when two setups disagree at the same time, since "no signal" is itself a decision with a cost.
- **Setup redundancy** — if two setups are highly correlated in when they fire, treat them as one vote, not two, or the AI will overweight confluence that isn't truly independent confirmation.

### Risk-aware, not just win-rate-aware
- **Distribution shape, not just average** — a 40%-win-rate setup with huge right-tail winners is very different from a 60%-win-rate setup with capped upside. Log skew/kurtosis of outcomes per setup, not just mean R.
- **Correlated loss risk across setups** — if several setups can all lose together from the same macro event (e.g. a surprise Fed comment), they aren't truly diversified; the AI shouldn't stack full risk on "3 confirmations" that are actually one bet.
- **Max adverse excursion before target hit (on winners)** — tells you whether stop placement is even compatible with the setup's real behavior.

### Model hygiene
- **Out-of-sample lockbox** — hold back a chunk of recent data the AI never sees during pattern-mining, to sanity-check conclusions before trusting them live.
- **Multiple-comparisons correction** — with 10 setups × dozens of context slices, some "edges" will be statistically significant purely by chance. Discount for how many slices were tested, not just report the best-looking ones.
- **Explicit "I don't know yet" state** — for setup/context combinations with too few samples, default to neutral rather than force a verdict.

### General gold market behavior baseline (independent of any setup)
This is a different layer from setup-specific edge — it's a continuously-updating profile of how gold behaves *in general*, that every setup signal and confidence score can be compared against. Doesn't depend on any setup firing; it's built purely from ongoing price/volatility data.

- **Typical range by session** — what counts as a "normal" London/NY/Asian session range, so the system can tell when today is unusually large or small before any setup even fires.
- **Volatility rhythm** — gold's characteristic compress-then-expand pattern (quiet build-up, sharp spike) rather than even drift. Learning this rhythm distinguishes "normal pre-breakout quiet" from "dead, low-opportunity conditions."
- **Reaction tendencies at levels** — does gold typically wick through round numbers and reject, or consolidate at them first? Does it usually retest a broken level before continuing, or run without looking back? These are stable "personality traits" that hold across many different setups.
- **Trend persistence vs mean-reversion character** — statistically, is gold more trend-following or mean-reverting on M15 over the accumulated data (ties to the Hurst exponent / autocorrelation idea in Section 6)? This can drift across multi-month regimes.
- **Typical response magnitude to catalysts** — not just "NFP causes volatility" but *how much*, on average, and how that drifts over time as markets desensitize/re-sensitize to specific releases.
- **Baseline correlation behavior** — the "normal" strength of the DXY/real-yields relationship, so the system can detect when gold is trading *unusually* decoupled from its usual macro anchors (itself a signal, per Section 5.6).

**Why it matters:** this baseline is what lets the AI say "this signal fired, but today's volatility is already 2x gold's normal Tuesday range" or "this is a totally ordinary pullback, nothing anomalous" — context no single setup captures alone. It's the difference between the AI knowing individual patterns and having actual situational awareness of the instrument. It runs continuously in parallel with the setup-specific edge work, not as a replacement for it.


- **Confidence-linked position sizing** — instead of binary take/skip, output a confidence score that scales size, so a marginal-edge signal is taken small rather than filtered entirely.
- **Post-trade attribution log** — after each live trade, record which factors the AI cited, so later you can check whether its stated reasoning actually correlated with outcomes.

---

## 4. Proposed AI Architecture: Two Stages, Not One Model

1. **Offline research layer** (runs periodically — daily/weekly, not in the trade path):
   - Analyzes accumulated signal/outcome data
   - Finds conditional edges across the slices above
   - Can use an LLM to read the aggregated stats and produce human-readable "why" explanations — good fit for narrative pattern-finding
2. **Live decision layer** (fast, deterministic):
   - A lightweight scoring function or gradient-boosted model that applies the thresholds/rules the research layer discovered
   - No LLM calls in the actual trade-execution path — adds latency, cost, and non-determinism that live orders shouldn't carry

### 4.1 Continuous Learning — What Updates Automatically vs. What Needs Review

**Updates automatically, on a schedule (safe, continuous):**
- **Edge tables refresh** — as new trades and signals accumulate, conditional win-rate/MFE stats per setup+context slice recompute (daily/weekly), so the AI's picture of "when does this setup have edge" stays current rather than frozen at initial build.
- **Confidence decay weighting** — recent performance counts more than old performance automatically, so a fading setup gets down-weighted without manual intervention.
- **Catalyst/volatility context** — inherently live by nature (economic calendar, real-time ATR spikes), always current.

**Requires review before going live (risk control):**
- The **live decision-layer thresholds/rules** themselves should not auto-push from the offline research layer straight into live trading logic every cycle. That's how a bad data week (broker outage, data glitch, unusually thin holiday session) quietly corrupts real-money decisions.
- **Recommended pattern:** research layer proposes updated thresholds → they sit in a staging/review state → a human (or an automated significance/sanity check) approves before they go live. This is continuous learning with a human-in-the-loop gate, not a fully autonomous self-modifying system.

**Where ongoing learning pays off most:**
- Long-run pattern discovery improves the longer the system runs — more samples per context slice, better statistical confidence, catching seasonal or regime-shifting effects (e.g. a setup that only started working once a rate-cut cycle began).
- The post-trade attribution log (Section 3, Feedback loop) keeps this honest — it lets you check months later whether the AI's *stated* reasoning for confidence actually predicted outcomes, and retire factors that turn out not to matter.

**Risk to stay aware of:** fully automatic self-learning without the staging/review gate is how systems drift into overfitting live — the multiple-comparisons problem (Section 3, Model hygiene) gets worse, not better, the more the system "learns" unsupervised.


Running 10 setups + this AI layer is heavier than the single EA built previously — likely something like SQLite (or similar) for signal/outcome logging, plus a periodic Python job for the analysis. Fully doable on a small Oracle VM; the analysis job should run on a schedule (e.g. daily/weekly), not on every tick.

---

## 5. Risk:Reward Rules — AI-Determined, Not Fixed

**Baseline rule:** minimum RR of **1:3** on any trade taken. No fixed maximum — the AI determines how far a winning trade is allowed to run, based on setup confidence and live analysis.

### 5.1 Enforcing the floor (1:3 minimum)
- At signal time, compute the planned stop distance and the nearest justified target (see below).
- If the best justified target is less than 3x the stop distance, either:
  - Extend the target to the next valid structural level that clears 1:3, if one exists within reason, or
  - Discard the trade — don't force a 1:3 target onto a level with no structural support behind it.

### 5.2 How the AI should size the target beyond the floor
Rather than picking an arbitrary multiple, layer these:
- **Historical run-distance distribution** — for this setup + context (session, regime, confluence, etc.), pull the actual MFE distribution of past winners. Use it to set a probabilistically justified initial target, not a guess.
- **Confidence score** (from the edge analysis — sample size, conditional win rate, recency-weighted decay, confluence) scales aggressiveness:
  - Low confidence but still above the minimum-edge bar → aim near the 1:3 floor, take profit promptly.
  - High confidence → wider initial target, looser trail, let it run further.
- **Structural target zones** — next liquidity pool, daily/weekly high or low, round numbers — generally more reliable for gold than a blind fixed multiple, since price often reacts at these levels regardless of the setup's own logic.

### 5.3 Managing the trade once it's open (this is where "maximum any amount" actually gets captured)
- **Multi-tier partial exits**, e.g.: take a portion off at 1:3 (locks in the guaranteed minimum), another portion at a structure-based mid-target, and let the remainder ride with no fixed cap.
- **Asymmetric trailing stop** — loose early (so normal noise doesn't stop you out before the setup's thesis plays out), progressively tighter as the trade extends further into profit, so gains aren't given back on a reversal.
- **Confidence recalibration mid-trade** — if new signals support continuation (other setups aligning, momentum persisting, a liquidity sweep of the next level), the AI can widen the trail / extend the target further. If opposing signals appear, tighten the trail even if the 1:3 floor hasn't printed yet (the floor is an entry filter, not a promise to hold blindly to that level).
- **Time-based decay** — if a trade stalls for too many candles without progress, that's itself information; the AI should tighten management rather than assume the original thesis still holds.

### 5.4 Sizing implication
Letting winners run uncapped increases the variance/skew of outcomes on purpose (ties back to the "distribution shape" point in Section 3) — so position sizing per trade should scale with confidence tier, not be flat across all trades. A low-confidence 1:3 trade and a high-confidence "let it run" trade shouldn't carry the same risk allocation.

---

### 5.5 Concrete Trailing-Stop / Partial-Exit System (first defined version, to backtest and tune)

A hybrid of ATR-based and structure-based trailing, staged by R-multiple, modulated by confidence.

**Stage 0 — Entry to 1R: hands off**
No trailing yet. Stop stays at the original SL. Moving it early just gets the trade stopped out by normal noise before the setup's thesis has a chance to play out.

**Stage 1 — 1R reached: move to breakeven**
Once price reaches 1x the initial risk, move SL to breakeven + a small buffer (covers spread/commission, not a profit lock). Protects capital without capping upside.

**Stage 2 — 3R reached (the 1:3 floor): take partial profit**
- Close a portion of the position (e.g. 40–60%, confidence-scaled — higher confidence keeps more running).
- Move the stop on the remainder to lock a partial gain (e.g. 1.5–2R), not just breakeven anymore.
- This is the moment the "guaranteed minimum" from Section 5 actually gets banked.

**Stage 3 — beyond 3R: hybrid trailing on the remainder**
Two trail calculations run in parallel; use whichever is tighter/safer (never let the stop loosen):
- **ATR trail**: `stop = price − (k × ATR(14))` for longs (inverse for shorts). `k` shrinks as the trade extends further, so protection tightens as gains grow:
  - 3R–5R: k ≈ 2.5
  - 5R–8R: k ≈ 1.8
  - beyond 8R: k ≈ 1.2
- **Structure trail**: move the stop behind the most recent confirmed swing point (fractal/pivot) in the trade's direction. Only ever tightens, never moves backward.

**Confidence modulation**
- Higher-confidence trades: looser `k` values, smaller partial taken at 3R, more room to run.
- Lower-confidence trades (that still cleared the 1:3 entry bar): tighter `k`, bigger partial taken at 3R, protect gains sooner.

**Stagnation check**
If N candles pass with no new swing point forming in the trade's direction, tighten the trail an extra notch (or exit) — time without progress is itself information that the original thesis may be losing steam.

**Implementation note (ties to the existing EA):** the base EA already has broker minimum stop-distance auto-widening and a fix for TP staleness after stop widening — the trailing logic needs to reuse those same guards, since every trail update is a `PositionModify` call that has to respect Exness's stop/freeze level.

### 5.6 Catalyst / regime confidence — separate from technical confidence
Technical confidence (conditional win rate, sample size, recency-weighted decay) only captures how a setup behaves in "ordinary" market conditions. It doesn't capture moments where price moves far beyond its normal distribution because of an external catalyst — scheduled news, a surprise headline, or a liquidity-driven spike. This needs to be a **separate signal that multiplies against technical confidence**, not folded into the existing volatility-regime bucket:

- **Danger mode (pre/during a known catalyst)**: a scheduled high-impact release is imminent (NFP, FOMC, CPI). Technical setups become *less* trustworthy here, because the coming move will be driven by the news outcome, not the pattern. The AI should suppress confidence or stand down regardless of how clean the setup looks, based on minutes-to/from the scheduled event (economic calendar proximity).
- **Opportunity mode (post-shock continuation)**: news has just caused a violent, high-volatility move (spike candle, gap, high-volume liquidity sweep). If a setup then fires in the direction of that momentum, its true edge in this specific context can differ significantly — often stronger — than its normal edge, and should be logged and scored as its own distinct context bucket rather than lumped in with ordinary conditions.
- Needs a **real-time volatility spike detector** as well as calendar proximity, since gold also spikes on unscheduled catalysts (geopolitical headlines, surprise central bank comments) that no calendar will flag — e.g. current ATR or tick-range vs a rolling baseline, flagging candles that are way outside normal independent of any scheduled event.

**Resulting confidence formula (conceptual):** `final confidence = technical confidence × catalyst-context modifier`, where the modifier can suppress confidence heading into a known event, and defines a distinct edge profile for "post-shock continuation" setups vs "normal" ones.

> **Flag (2026-09-21):** treat "opportunity mode" as an untested hypothesis, not an assumed edge. A falsification study on index futures (MNQ, 2022-2025 events) found post-release drift sat entirely inside the first few bars after the release; from bar +6 onward, T-statistics were only ~0.1-0.7. Analogy only (not gold), but log this bucket separately and require it to earn its place in Test 2. The "danger mode" side is better supported: Metric J confirmed event magnitude differs significantly by release family (NFP > CPI > FOMC > GDP/PCE), so the catalyst modifier should be family-specific, not one shape for all events.

### 5.7 Strict 1:3 vs. Dynamic (AI-Determined) RR — Which Is Better

**Strict 1:3 (fixed target every time)**
- Pros: simple, fully deterministic, trivial to backtest and trust, no risk of the AI's judgment being wrong about "how far to let it run."
- Cons: caps upside exactly on the trades where the setup had real conviction — usually where most of a trend-following/breakout system's total profit comes from. Ignores confidence, structure, and catalyst context entirely.

**Dynamic (1:3 floor, AI-determined ceiling — the approach chosen in Sections 5.1–5.6)**
- Pros: captures right-tail wins a fixed system caps away; lets confidence, structure, and catalyst context actually matter; better long-run expectancy *if* the confidence scoring is genuinely predictive.
- Cons: much harder to validate — more moving parts (trailing logic, confidence score, catalyst modifier) means more ways to overfit or introduce a bug; harder to diagnose *why* a trade did what it did when something goes wrong; needs the full out-of-sample testing protocol (Section 6) before it can be trusted, not just intuition.

**Verdict:** the dynamic system is better in principle, but only proven better once it clears the Jan 2025→now forward test and a demo-live stretch — not from day one on intuition alone.

**Recommended path:** build and ship the dynamic version, but run it in **parallel/shadow mode** against a strict-1:3 baseline for a period. If the dynamic system's forward-tested expectancy doesn't clearly beat the simple baseline, that's a signal the confidence scoring isn't adding real information yet — and falling back to strict 1:3 is a legitimate, not inferior, interim choice while the confidence model is refined further.

---

## 6. Full Strategy / Analysis Reference Library

*A broad catalog of everything that can inform gold market analysis — not all of these should become literal standalone "setups." Many are better used as context filters/confidence modifiers feeding the AI decision layer rather than independent triggers (see Section 6.1 for how to tier these).*

### Technical / Price-Action Based
- Market structure: swing high/low breaks, higher-highs/higher-lows sequencing, break of structure (BOS) vs change of character (CHoCH)
- Support/resistance & supply/demand zones: horizontal levels, prior day/week/month highs-lows, round numbers (2000, 2500, etc.)
- Trendlines & channels: trendline breaks, ascending/descending channel trades
- Chart patterns: head & shoulders, double top/bottom, triangles, flags/pennants, wedges
- Candlestick patterns: engulfing, pin bars/hammers, doji at key levels, three-bar reversal patterns
- Fibonacci: retracements (38.2/50/61.8%) for pullback entries, extensions for targets, confluence zones where multiple fib levels stack

### Smart Money / Institutional Concepts
- Liquidity sweeps / stop hunts: price grabbing obvious highs/lows before reversing
- Order blocks: last opposing candle before a strong impulsive move
- Fair value gaps / imbalances: unfilled gaps in price that often get revisited
- Market Structure Shift (MSS) — already implemented in the base EA
- Wyckoff phases (accumulation/distribution, spring/upthrust) — noted as a category; already excluded from the base EA as too subjective
- Inducement: minor liquidity grabs designed to trap early entries before the real move

### Indicator-Based
- Trend: moving average crossovers (e.g. 50/200), MACD, ADX for trend strength, Supertrend
- Momentum: RSI (overbought/oversold, divergence), Stochastic, CCI
- Volatility: Bollinger Bands (squeeze/breakout), ATR-based systems, Keltner Channels
- Volume-based proxies: MT5 forex/gold volume is tick volume, not true volume — On-Balance Volume, volume spikes relative to average

### Multi-Timeframe Frameworks
- Top-down analysis: HTF (daily/4H) for bias, LTF (M15/M5) for entry — HTF trend filter already implemented
- Timeframe confluence: same setup confirming across 2-3 timeframes simultaneously
- Session-based structure: Asian range as a reference box, London/NY breakout of that range

### Fundamental / Macro Drivers (gold-specific — where gold differs most from FX pairs)
- Real yields: gold is heavily inversely correlated with US 10-year real (inflation-adjusted) yields
- US Dollar Index (DXY): inverse correlation, though it decouples during risk-off/safe-haven flows
- Fed policy expectations: rate decisions, dot plot shifts, Fedspeak tone
- Inflation data: CPI, PCE — gold's traditional inflation-hedge narrative
- Safe-haven/risk-off flows: geopolitical tension, equity market stress, banking crises
- Central bank buying: official-sector gold purchase trends (slow-moving macro backdrop, not a trade trigger)
- ETF flows: GLD and other gold ETF holdings as a sentiment proxy for institutional positioning

### Intermarket / Correlation Analysis
- DXY correlation regime: track whether gold's normal inverse-DXY relationship is currently holding or has decoupled (decoupling itself is informative — often signals a safe-haven regime)
- Gold/silver ratio (XAGUSD relationship) as a regime indicator
- US equities (S&P 500): risk-on/risk-off cross-check
- Bond market: US 10-year yield/TLT as the real-yields proxy in real time
- Oil: broader commodity-complex risk sentiment, less direct than DXY/yields

### Sentiment / Positioning
- COT (Commitment of Traders) report: weekly CFTC data on large speculator vs commercial positioning in gold futures — contrarian extremes indicator (weekly, not real-time)
- Retail sentiment data: broker-published long/short ratios (contrarian signal when heavily skewed)
- Options market: put/call skew on gold options, implied volatility levels ahead of events

### Seasonal / Calendar-Based
- Day-of-week effects: gold may behave differently early vs late week
- Month-end/quarter-end flows: fund rebalancing
- Historical seasonality: documented tendencies around certain months in various studies — test on own data rather than trusting folklore
- Options expiry: large expiries can pin price near round strikes

### Volume / Order Flow
- Tick volume spikes: proxy for real volume/activity
- Volume profile: identifying high-volume nodes as support/resistance
- Footprint/order flow tools: more common on futures gold (COMEX) than CFD gold — real order flow becomes available only with COMEX data access

### Statistical / Quantitative
- Mean reversion vs trend-following regime detection: Hurst exponent or simple autocorrelation to classify current regime
- Z-score/statistical extremes: standard deviations from a moving average
- Volatility clustering models: GARCH-style thinking — high-vol periods cluster, informs dynamic position sizing
- Machine-learning feature mining: essentially what the AI decision layer already is — clustering/decision-tree analysis over the conditional edge slices

### Event/News-Based
- Economic calendar-driven straddle/breakout systems: trading the volatility expansion around NFP/FOMC/CPI directly, rather than avoiding it
- Post-event continuation vs fade: separate strategy class for "does the initial spike continue or reverse" — already flagged as its own context bucket in Section 5.6

### 6.1 Tiering This List — Setups vs. Context Modifiers

Running all of the above as literal, independent standalone setups is a recipe for redundant, correlated signals (the redundancy problem from Section 3) and an unmanageable multiple-comparisons problem. Recommended tiering:

- **Tier 1 — actual detection setups (the ~10 core setups)**: pick concrete, testable candidates mainly from Technical/Price-Action, Smart Money Concepts, and Indicator-Based categories — things that produce a discrete, timestamped "signal fired" event.
- **Tier 2 — context filters / confidence modifiers**: Fundamental, Intermarket/Correlation, Sentiment, Seasonal, and Event/News categories generally don't fire standalone trade signals — they modify the AI's confidence in a Tier 1 signal (this is the same pattern as the catalyst/regime confidence work in Section 5.6, generalized).
- **Tier 3 — data-dependent / defer**: anything needing data sources not readily available through MT5 (COT reports, options skew, true COMEX order flow, ETF flow data) — valuable, but requires separate data feeds/APIs to be wired in. Treat as a future enhancement once the core system is proven, not a day-one requirement.

---

## 7. Testing Protocol: Three-Stage Validation Series

### 7.1 Walk-Forward Validation Structure
- Don't rely on a single train/test split (e.g. years 1–8 learn, 9–10 test) — gold's behavior has shifted across regimes (QE era, 2022+ rate-hiking cycle, various crisis-driven safe-haven stretches), so one split risks the result being lucky/unlucky depending on that window's regime.
- Use **multiple walk-forward windows**: learn years 1–6, test 7–8; learn 1–8, test 9–10; learn 1–9, test 10→now. Consistent performance across several splits is a much stronger signal than one good result.
- Within the training years themselves, split further into a **fit** period and an internal **validation** period (e.g. years 1–6 fit, 7–8 validate/tune) before ever touching the final held-out test years — otherwise every parameter still gets tuned against the whole training block.
- **Check first**: confirm Exness/MT5 actually provides 5–10 years of clean M15 history (no gaps, consistent spread/tick quality) before planning the split — the Strategy Tester's data availability should be verified, not assumed.
- Judge "understanding," not just PnL: do the specific conditional edges discovered in training (session, regime, confluence) still hold *directionally* in the forward period, even if magnitude shifts? Patterns transferring with a performance dip is healthy; performance holding while the underlying reasons look totally different is a red flag of luck rather than learning.

### 7.2 The Three-Stage Series
1. **Test 1 — Understanding**: the baseline profiler alone (Section 3's market-behavior baseline), scored on forecasting/calibration accuracy — no setups, no trades. Must be validated first: if the baseline's context is poorly calibrated, everything built on top of it (setup confidence, catalyst modifiers) is being fed bad information, and Test 2 failures would be undiagnosable.
2. **Test 2 — Setup edge validity**: add the 10 setups on top of a validated, baseline-aware system; run the standard walk-forward PnL/expectancy test (Section 7.1).
3. **Test 3 — Execution reality**: demo-live, to catch what backtesting can't — slippage, real fills, VPS/connection issues.

### 7.3 Test 1 Full Spec — Scoring "Raw Understanding"
Since the baseline generates no trades, it can't be scored on win rate/profit factor — it needs forecasting/calibration metrics instead:
- **Range prediction accuracy** — does the predicted range distribution for each session (Asian/London/NY) actually contain the realized range at the rate it should (e.g. an 80%-confidence range containing the outcome ~80% of the time across many sessions — a calibration test, not a point-guess test)
- **Volatility regime classification accuracy** — classify each day as high/normal/low volatility in advance, score against what actually happened
- **Anomaly-flagging precision** — when it flags "today is unusual vs baseline," check retrospectively how often that corresponded to a confirmed later anomaly vs a false alarm
- **Correlation-regime tracking** — does its read on DXY/gold correlation strength match a direct statistical correlation calculation over the same window
- **Trend/mean-reversion character** — does its regime classification match independent objective measures (Hurst exponent, ADX) over the same period
- **Level-reaction prediction** — reject vs break-through at key levels, scored across many level touches
- **Session-open behavior prediction** — anticipated vs actual volatility expansion at London/NY open
- **Catalyst magnitude prediction** — expected move size ahead of scheduled releases vs realized move
- **Weekend gap behavior** — predicted gap size/direction vs actual at each Monday open
- **Distribution shape check** — implied skew/fat-tails vs realized skew/kurtosis of forward returns, not just the mean
- **Lead-lag alignment** — if it's learned "DXY leads gold by X," does that hold when measured directly against forward data
- **Cross-timeframe consistency** — does the "understanding" generalize to H1/H4, or does it only look coherent on the trained timeframe

**The two most important checks, done for every metric above:**
- **Benchmark against a naive baseline** — e.g. "today's range = yesterday's average range" or a random-walk gap assumption. A metric that only modestly beats a naive baseline is a much weaker result than it looks in isolation; without this comparison, "80% accurate" is meaningless.
- **Statistical significance / sample size** — a 1–2 year forward window gives ~250–500 trading days, plenty for range/volatility calibration but thin for rarer events (catalyst reactions, weekend gaps). Report confidence intervals, not just point accuracy — don't declare "it understands NFP reactions" off a sample of 8–16 releases.

**Additional check:** training-window sensitivity — does the baseline's "understanding" stay roughly stable whether trained on 5, 8, or 10 years? A picture that shifts drastically with training length signals instability rather than genuine, persistent understanding of gold's character.

### 7.4 Test 1 Revisions from External Validation Review (added 2026-09-21)

*Source: literature/forum review of Phase 1-3 methodology (see gold-ea-progress.md, "External Validation Review"). These revise how Test 1 metrics are scored so results match this section's own spec. Sources were mostly academic papers plus broker/educational blogs (weak evidence); two real trader-forum threads only.*

**Scoring rules that apply to every Test 1 metric (tightening 7.3's "two most important checks")**
- **Baseline strength.** Report against the *strongest* simple baseline, not just the weakest. For range prediction: yesterday's single range (weak), trailing 5- and 20-day mean range (ATR-style), and a HAR-type model if feasible. Beating only a one-observation naive baseline is a low bar.
- **Significance, not win counts.** Use block-bootstrap or Diebold-Mariano-style tests and report confidence intervals/p-values. "Beats naive in 4/6 combos" is not inference, especially when margins are ~1-3%.
- **Window matrix is robustness, not replication.** The 6 combos share heavily overlapping test periods, so they are not independent tests. Say so when reporting.
- **Multiple-comparisons accounting.** Log how many tests were run (metrics x sessions x combos) and use a stricter hurdle than p<0.05; some findings will be luck. This applies Section 3's "Model hygiene" rule to Test 1 itself.

**Metric-specific revisions**
- **Range prediction:** add the calibration test 7.3 actually specifies - empirical coverage of 80%/90% predicted intervals per session (e.g. from training-window residual quantiles) - alongside MAE. Keep the percentage-of-prior-close form (fixed-dollar assumptions have now caused three bugs). Treat Asian as unproven until re-tested with the stronger baselines.
- **Level-reaction:** compare Brier scores to the class-frequency (entropy) floor. The pooled baseline (~0.662) already sits at that floor, so current features show no predictive value; describe the layer as descriptive/detection-only until a feature beats the floor.
- **Volatility regime / cross-timeframe (Metric I):** intraday volatility has strong time-of-day seasonality, which can mask clustering. Remove/adjust for time-of-day before defining H1 regimes and re-test before concluding "no H1 signal." Also resolve the tension: if regime confidence only works at D1/H4 but setups and this design profile M15, D1/H4 confidence cannot directly inform M15 signals. **Result (2026-09-21):** re-test done. Time-of-day contamination confirmed (P(high) by hour 0.04-0.69 on original labels, flat after adjustment). With time-of-day-relative regimes, previous-bar persistence is significant at H4/H1/M30 (Brier gain ~4-6% vs majority) while ~33-day persistence is negligible - so the original H1 "no signal" was mainly a horizon problem and the D1/H4-only restriction is withdrawn. Use time-of-day-relative regimes at short lags for intraday confidence; details in gold-ea-progress.md.
- **Catalyst magnitude:** price-move magnitude is not spread widening. Validate the release-family split against directly measured spreads (Exness sample) before changing SPIKE_TEMPLATE. Use a longer post-window for FOMC (slower decay than payrolls), non-parametric tests for skewed magnitudes, and note GDP/PCE mix multiple estimate releases and may coincide with other same-time releases.
- **Trend/mean-reversion (Hurst):** see the estimator caveat in 9.3; keep the effect-size caveat about overlapping windows.
- **Session boundaries:** confirm fixed-UTC session windows account for daylight saving (London/NY opens shift; UK and US switch on different dates), consistent with 9.7's timezone rule.
- **Correlation-regime (K):** use returns, not price levels; choose windows/thresholds from own data (published baselines vary widely, ~-0.45 on 30-day vs ~-0.85 on 60-month windows); test whether a regime persists out of sample.
- **Lead-lag (L):** verify timestamp alignment between the gold feed and the broker DXY feed first (e.g. against a known event); a one-minute offset can create a fake lead-lag.

**Carry into Test 2:** require P&L results with realistic spreads/slippage, and keep a running count of setups/parameters tried (deflated-Sharpe / probability-of-backtest-overfitting logic).

### 7.5 Test 1 findings to date (added 2026-09-21, after the validation review)

*Status: E is descriptive, J needs spread validation, K has a volatility-control check pending. Effect sizes are % Brier gain over the majority baseline unless stated. All windows: the pre-committed 6-combo walk-forward matrix (overlapping test periods - robustness, not independent replication).*

**Established (usable as calibrated inputs)**
- **Range expectation:** an adaptive trailing 5-20 session mean range (as % of prior close) is at least as good as any long-window training-mean model, for full sessions (A) and opening ranges (G). Interval calibration: unconditional quantile intervals cover ~80%/90% for London/NY; under-cover for Asian under rolling windows.
- **Intraday volatility persistence (I):** with time-of-day-relative regimes, previous-bar persistence is significant at H4/H1/M30 (~4-6%); same slot previous day ~1.4-1.8%; ~33-day lag ~0. Use short lags and time-of-day-relative labels.
- **Session-level daily regime persistence (C):** Asian only (~3% at lookback >= 100; not at 60). London/NY: none.
- **Anomaly flags (H):** opening-range spike flag - precision lift vs base rate ~1.4x-2.7x against rest-of-session ground truth (Asian 2.7x, London ~1.8-1.9x, NY 1.4-1.8x; NY DST-aware weakest); calendar flag ~1.7x London, ~1.8x NY (DST-aware mapping). Risk indicators only: ~60% of flagged sessions are not high-volatility.
- **Event magnitude (J, Part 1):** differs significantly by release family (NFP > CPI > FOMC > GDP/PCE); family-specific spike scaling recommended, pending direct spread validation.

**Not supported by the data**
- Trend / mean-reversion regime persistence (Hurst withdrawn; variance-ratio test rho ~ -0.02, CI -0.16..+0.13).
- Level-reaction prediction from tier (Brier at the base-rate floor).
- Weekend-gap persistence.
- London/NY conditional regime signal claimed in the original Metric C.

- **Gold/DXY relationship (K, L; 2021-07 to 2025-12):** contemporaneous, strongly negative (1-min correlation -0.38, -0.66 in the 08:25-08:45 New York release window), with no exploitable lead-lag at minute scale. The strength varies a lot by 10-day block (10th/90th percentile -0.69/-0.19) and persists (+0.65 rank correlation between consecutive blocks; volatility-control check pending), and was weakest in 2025 (-0.31). Use the trailing ~10-day correlation as a state variable telling the decision layer how much weight to give a simultaneous DXY move; do not treat DXY as a leading indicator.

**Unresolved:** E (distribution-shape stability, descriptive), J spread validation, K volatility-control check, Asian regime lookback sensitivity, D1-scale power, 2026 holdout.

---

## 8. Risk Controls & Operational Resilience

### 8.1 Risk management above the single-trade level
- **Max daily/weekly loss limit** — a circuit breaker that halts new entries if drawdown hits a set % in a day/week, regardless of how good the next signal looks.
- **Max concurrent exposure** — a hard cap on total risk-on when multiple setups fire near-simultaneously (ties to the correlated-loss-risk point in Section 3).
- **Equity-curve-based sizing** — reduce position size after a losing streak, scale back up after recovery, rather than flat sizing regardless of recent performance.

### 8.2 Broker/execution mechanics
- **Swap/rollover rates** — gold typically has a triple-swap day (commonly Wednesday); matters for anything held overnight.
- **Margin and leverage limits** — behavior as margin level drops (margin call / stop-out level), especially relevant on a small account.
- **Execution model specifics** — market vs instant execution, requote handling, max acceptable slippage before the EA cancels/retries an order.
- **Weekend hold policy** — explicit rule on closing or reducing positions before Friday close, given gold's gap behavior (tested in Section 7.3, but needs an operating rule here).

### 8.3 Operational resilience / failure modes
- **Kill switch** — manual and automatic override to flatten everything and stop trading (VPS outage, broker feed going stale, repeated EA errors).
- **Reconnection reconciliation** — after a dropped connection, the EA re-checks its internal state against the broker's actual open positions before resuming, so it can't get out of sync.
- **Stale/bad data detection** — check that the price feed isn't frozen and a candle isn't garbage before trusting it as a signal.
- **Alerting** — push notifications (Telegram/email) for disconnects, large drawdown, or repeated errors, so problems don't sit unnoticed on an unattended VPS.

### 8.4 Model governance beyond the staging gate (extends Section 4.1)
- **Live-vs-backtest divergence monitoring** — track live expectancy against what the walk-forward test predicted; flag meaningful drift rather than waiting for a scheduled review.
- **Rollback plan** — if a newly promoted threshold set underperforms, revert quickly to the last known-good version.

### 8.5 Behavioral guardrails as system rules
- **Overtrading cap** — max trades per day/setup even if signals keep firing.
- **Cooldown after a loss** or a stopped-out trade on the same setup, so the system doesn't immediately re-enter on noise.

### 8.6 Calendar coverage beyond NFP/FOMC/CPI
- ECB and BoJ decisions move DXY (and therefore gold) indirectly.
- Illiquid stretches like Christmas/New Year week behave differently and are worth flagging as their own regime rather than just "low volatility."

### 8.7 Legal/tax housekeeping
- Not financial or legal/tax advice — just a checklist item: confirm the broker's terms allow VPS-hosted EAs, and check how trading profits are taxed in your jurisdiction, since that affects whether trade logging should be tax-report-friendly from day one rather than retrofitted later.

---

## 9. Phase 1 AI Foundation — Technical Stack

*Covers the baseline profiler / Test 1 build specifically. Framing: Phase 1 is statistical/calibration modeling — distributions, classification, correlation — not an LLM system. An LLM would be slower, non-deterministic, and worse than direct statistics for the forecasting itself here.*

### 9.1 Data source
- The official **MetaTrader5 Python package** (pip-installable) connects directly to a running MT5 terminal and pulls historical OHLC bars and tick data — no manual CSV exports needed.
- Pull once for a historical backfill (as far back as the broker's clean data goes, per Section 7.1's depth check), then a scheduled job appends new bars going forward.

### 9.2 Storage
- **SQLite** for raw OHLC/ATR/volume history and the signal/outcome log — matches Section 3's data design, zero setup, fine for solo-project scale on a small VPS.
- **DuckDB** (or plain pandas) for the heavier analytical work — rolling distributions, calibration checks across years of bars. DuckDB runs SQL-style aggregations directly over SQLite/CSV data very fast with no server to manage; not mandatory, but removes a lot of pandas-memory pain once crunching years of M15 bars.

### 9.3 Core computation stack
- **Python** — pandas/numpy for data handling.
- **scipy / statsmodels** — distribution fitting for range-prediction confidence intervals, autocorrelation for trend-vs-mean-reversion character, statistical significance testing (Section 7.3's confidence-interval requirement).
- **pandas-ta** (or ta-lib for the C-backed version) — ATR, ADX, and other indicators feeding the volatility-regime classifier.
- **hurst** (small pip package) — for the Hurst exponent check called out in Sections 6 and 7.3. **Result (2026-09-21): the Hurst check (Metric D) showed no evidence of persistence** - its 'gains' were reproducible on pure noise (+5.9% on average) because of overlapping windows; replaced by a variance-ratio test (`trend_character_v3.py`). Treat any Hurst-based confidence as unsupported until that test passes. **Caveat (2026-09-21):** rescaled-range (R/S) Hurst estimates are known to be biased (toward ~0.7) and need large samples; generalized Hurst (GHE) or DFA estimators show lower bias/variance. Confirm which estimator the package/script uses (as far as I know the `hurst` package is R/S-based) and consider GHE/DFA; treat Hurst-based conclusions as low weight either way.
- **scikit-learn** — only if volatility-regime or anomaly-flagging classifiers need more than threshold rules. Start with plain thresholds first; only reach for ML if thresholds prove too crude — simpler to validate and debug.

### 9.4 Scheduling
- Plain **cron** on the VPS running a Python script daily/weekly to append new data and refresh rolling stats. No need for a heavier orchestration tool (Airflow/Prefect) at this scale.

### 9.5 Where an LLM actually belongs (not Phase 1)
- Per Section 4, the LLM's job is the offline research layer — reading aggregated stats tables and producing human-readable "why" explanations, once there's enough accumulated setup/outcome data (Phase 2, after the 10 setups are logging).
- For Phase 1 specifically, the closest legitimate use is generating readable summaries of calibration results for review — not making the forecasts themselves.

### 9.6 Reporting/sanity-checking
- **matplotlib** or **plotly** for calibration curves (predicted-vs-actual reliability diagrams) — the visual reveals whether an "80% confidence range" is really behaving like 80% far faster than staring at a table.

### 9.7 Engineering practices (easy to skip, costly if skipped)
- **Timezone handling** — MT5 server time, broker timezone, and UTC are usually all different. Session boundaries (Asian/London/NY) are meaningless if this isn't nailed down precisely before any calibration work starts; get it wrong and every "session range" stat is silently off.
- **Data cleaning/validation** — check historical bars for gaps, duplicate timestamps, zero-volume/broken candles before trusting them for calibration. Garbage bars quietly corrupt every downstream statistic.
- **Environment reproducibility** — a `requirements.txt` (or venv) pinning exact package versions, so a VPS rebuild or a second machine doesn't silently break things.
- **Version control (git)** for the actual Python code, not just this design doc — once thresholds and calibration logic change over time, it matters exactly which code produced which backtest result.
- **Config externalization** — session times, thresholds, lookback windows living in a config file/table rather than hardcoded in scripts, so tuning doesn't mean hunting through code.
- **Job-level logging** (separate from trade-error alerting in Section 8.3) — so a weird number from a scheduled calibration run leaves a log trail showing what it processed, not just a silent bad output.

---

## 10. Open / Next Steps

- Build the general market-behavior baseline profiler first (or in parallel with) the 10 setups — it only needs raw price/volatility history, not setup signals, so it can start accumulating data immediately and give every setup real context from day one instead of being retrofitted later
- Design the actual data schema for the signal log (fields listed in Sections 2 and 3)
- Decide how the 10 setups should log consistently (shared format/interface)
- Prioritize which of the Section 3 factors to build first vs defer
- Decide on the specific model/approach for the live decision layer (rules engine vs gradient-boosted model)
- Define the exact partial-exit tiers and trailing-stop logic for the 1:3-minimum / uncapped-maximum RR system
- Build out the testing protocol per Section 7: Test 1 (baseline understanding, no setups) → Test 2 (setup edge, walk-forward) → Test 3 (demo-live execution reality). Confirm the AI's edge-mining respects each window's cutoff so tests stay genuinely out-of-sample
- Stand up the Phase 1 technical stack (Section 9) and run Test 1's calibration metrics (Section 7.3) before building the 10 setups
- Implement the risk controls and operational resilience items (Section 8) alongside the EA build, not as an afterthought — the kill switch, daily loss limit, and alerting should exist before any live/demo run
- Run the dynamic RR system in parallel/shadow mode against a strict-1:3 baseline; only fully commit to dynamic RR once its forward-tested expectancy clearly beats the fixed baseline
- Apply the Section 7.4 revisions before treating any Test 1 result as final: stronger baselines and interval-coverage test for range prediction, significance tests, H1 deseasonalized re-test, DST check on session windows, spread-based validation before editing SPIKE_TEMPLATE
