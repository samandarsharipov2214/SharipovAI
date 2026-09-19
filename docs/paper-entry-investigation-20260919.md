# PAPER entry investigation — 19 September 2026

Baseline build: `e4ec31c2e2c0ad23767337dad7830faf4a1730c3`.
Canonical database scope: `2ba720c9995d8d3653ba`.
Change ledger: `astra-paper-prospective-edge-20260919`.

## Decision and root cause

Every new BUY now needs prospective economic support. Previously
`CouncilAuthorizedPaperLoop._anti_churn_buy_block_reason` returned success when
there was no previous close. On subsequent entries, absent expected edge fell
back to **absolute past price movement** since the previous close. Both an
upward and downward move could authorize another BUY. That is neither a
forecast of future return nor coverage of future transaction costs.

The actual frozen `CandidateEvidencePacket`, stored TradingCandidate and cost
snapshots contain **no prospective edge or calibrated uncertainty forecast**.
The economic observer correctly returns `expected_net_edge_percent=null` and
`INSUFFICIENT_EVIDENCE`; its descriptive historical mean is not alpha.
The old optional expected-edge aliases have no active canonical producer.
Thus this correction intentionally makes current new BUYs WAIT. Releasing this
containment requires a separately validated, timestamped, unit-defined forecast
producer with uncertainty and evidence provenance; attaching an arbitrary score
to an alias is not that validation.

Unknown required costs now BLOCK. The existing 1.5 cost cushion remains; it is
not a calibrated uncertainty estimate. Stops, take profits, position sizing,
Risk/Security, fees and the default post-stop **observe** mode are unchanged.
Existing positions continue protective and Council-authorized exits. New
observations/entries identify `paper-prospective-edge-v1:post-stop-observe`;
carry-in exits retain their original entry policy/build identifiers.

Nine regression cases failed against the baseline: first-entry missing edge,
both signs of large past movement after stop/TP, and missing/nonfinite/boolean
edge values. A real canonical-runtime test also proves that a valid GC BUY
authorization cannot consume authorization, spend cash or open a position when
the final economics gate waits. Execution/settlement tests explicitly stub the
economics precondition; the dedicated entry tests use the actual gate.

## Reverified economics and recent change

Read-only, indexed queries exported 107 cohort legs plus two explicit legacy
carry-in entries, 57 linked decisions and their evidence. No production history
was rewritten. All 52 pairs reconcile quantity and
`(exit_fill - entry_fill) * quantity - entry_fee - exit_fee`.

| Metric | All 52 | Earlier 35 | Last 17 |
|---|---:|---:|---:|
| Wins / losses | 25 / 27 | 10 / 25 | 15 / 2 |
| Net USDT | 1.8785186275 | -0.9979272447 | 2.8764458722 |
| Net expectancy USDT | 0.03612536 | -0.02851221 | 0.16920270 |
| Profit factor | 1.5490 | 0.6857 | 12.6885 |
| Pair fees USDT | 0.76489107 | 0.51933494 | 0.24555613 |
| Pair turnover USDT | 764.8911 | 519.3349 | 245.5561 |
| Average winner USDT | 0.21200127 | 0.21774937 | 0.20816920 |
| Average loss USDT | -0.12672271 | -0.12701684 | -0.12304610 |
| Realized pair drawdown USDT | 1.68546005 | 1.68546005 | 0.12471301 |

These drawdowns exclude intratrade equity; portfolio maximum drawdown is **not
established** by this bounded export. Five positions were open at capture.
The exit-version cohort also includes two legacy-entry closes, which must not
be attributed to a new entry policy. A strict 16 September 00:00 UTC cutoff is
18 closes, **16W/2L, +3.1365144922**. The owner's 15W/2L is the last 17 closes,
after the 16 September 20:02 UTC XRP winner.

The same `e4ec31c2` entry build produced 4W/10L, -0.4465249481 before the recent
17. There was no intervening trading-code deployment or exit-threshold change.
Recent average entry notional was 7.13 versus 7.43 USDT; mean spread was 0.62
versus 0.65 bps. Mean GC confidence fell from 92.50 to 90.45; directional quality
was approximately unchanged (80.63 to 81.03). Higher confidence did not explain
the improvement. The recent median holding time was 15.13h versus 3.42h.

All five symbols lost money in the earlier group and gained in the recent
group. Recent net contributions were BNB +0.3815, BTC +0.4212, ETH +0.5252,
SOL +0.7782, XRP +0.7703 USDT. The largest recent winner, +0.3070, represents
10.7% of recent net PnL. Four recent entries were made with negative rolling
24h change and later profited in a recovery; the earlier group also contained
four such entries. Persisted regimes are only rolling-change/turnover proxies,
not measured intraday volatility or trend structure.

The supported explanation is a market-path change: the same long-biased policy
experienced sustained recoveries/continuation across symbols instead of repeated
reversals. Average win/loss economics stayed similar while exit frequencies
changed. This is an inference from entry/exit observations, not causal proof
about news, learning or Astra. The earlier group had 18 post-stop observations
that would have triggered the disabled 24h veto; the recent group had three.

## Re-entry diagnostics, without threshold selection

`python -m tools.paper_entry_diagnostics --evidence EXPORT.json --output REPORT.json`
uses at most 2,000 legs. Only prior, already-persisted same-symbol closes can
affect an entry. Both time periods were already observed; neither is a holdout.
The following are **retained baseline pairs**, not replacement-entry backtests.

| Cooldown | After stop: retained W/L; net; PF | After TP: retained W/L; net; PF |
|---|---|---|
| 15m | 24/17; +3.005456; 2.433 | 19/19; +1.532627; 1.636 |
| 30m | 23/16; +2.896712; 2.473 | 18/19; +1.327557; 1.551 |
| 1h | 23/14; +3.147672; 2.835 | 16/19; +0.918632; 1.381 |
| 2h | 23/14; +3.147672; 2.835 | 15/18; +0.845622; 1.369 |
| 4h | 22/14; +2.952020; 2.721 | 15/18; +0.845622; 1.369 |
| 6h | 22/14; +2.952020; 2.721 | 15/18; +0.845622; 1.369 |
| 12h | 19/14; +2.271324; 2.324 | 14/18; +0.654478; 1.285 |
| 24h | 18/13; +2.194654; 2.370 | 14/18; +0.654478; 1.285 |

The JSON report additionally includes fees, turnover, expectancy, average
winner/loss, realized drawdown and symbol/regime breakdowns for each screen.
The 24h stop rule would also remove seven winners. No duration is activated or
selected from these outcomes. A new timestamp or expired timer alone is not
materially new evidence supporting a failed hypothesis.

For the actual correction, every captured new entry lacks a forecast. A flat
abstaining candidate would have zero trades/fees/turnover/PnL; PF and expectancy
are undefined. This removes winners as well as losers and does **not** demonstrate
improved profitability. Live carry-in PnL must be reported separately. There are
no fabricated delayed entries, cash simulation, or hindsight deletion of losers.

## Bounded runtime organ audit

All active components below are instantiated by the running dashboard startup
path; runtime HTTP and linked persistent records establish operation. Merely
importing their classes was not used as evidence of operation.

| Component / implementation | Actual input, persistence and consumer | Active effect / health |
|---|---|---|
| Market: `SharedVerifiedMarketStream` | Bybit WS, REST BBO, multi-exchange quotes; `council_market_evidence`, raw market observations; Council/fills | Live verified stream, measured age 0.809s, no fallback. Regime/volatility use crude 24h proxies. |
| News: `news_intelligence.network`, `NewsHub` | Real RSS/official feeds; `news_memory`, `news_article_evidence`, `news_fetch_observations`; DB Council reader | Worker running; 7 active / 5 idle sources. Directional interpretation defective, detailed below. |
| Council: traced `AutonomousCouncilProposalProvider` | Market, NewsHub, risk and cash; `autonomous_council_runtime`, DQ assessment events, news/risk/cost/portfolio snapshots | Real proposals. Price-consensus/liquidity recommendations duplicate market direction. |
| Decision Quality: `DecisionQualityService`, `directional_quality_from_payloads` | Stored Council opinions; `decision_quality` events, `trading_candidates` | V2 quality/agreement affects GC. Legacy learned weighted assessment is stored but replaced by `_effective_v2_assessment`. |
| General Controller: `GeneralControllerV2` | Directional scores plus risk/portfolio/security gates; `paper_v2_decisions` | Authoritative BUY/SELL/WAIT. Historical `shadow:true` label is misleading: `paper_authority:true` and consumed decisions prove activity. Legacy provider directive is audit-only. |
| Risk: `CanonicalRiskService`, gate adapter | Verified prices, turnover, drawdown, positions; `risk_assessments`; GC and final loop | Active veto. 24h stop memory is persisted/observed, not enforced. |
| Security: canonical PAPER boundary / candidate validator | Environment, candidate identity, no live approval; V2 gates and single-use consumption | Active veto/structure checks; all exchange-write flags off, kill switch on. |
| Portfolio: loop accounting / sizing gate | Cash, positions, execution estimates; `portfolio_snapshots`, `autonomous_paper_state` | Real persistent PAPER accounting and budget limits. No fee/quantity reconciliation mismatch in 52 pairs. |
| PAPER: `CouncilAuthorizedPaperLoop` | Single-use canonical authorization, BBO, dynamic instrument rules; `paper_trades:<scope>`, pending intents | Active. Corrected final economics boundary now abstains on unknown edge. |
| Settlement: `settle_exit`, pending-settlement recovery | Actual virtual close and entry identity; `paper_decision_settlements` | 52/52 linked settlements, side/outcome preserved, recovery path regression-tested. |
| Learning: `SelfLearningSupervisor`, attribution, economic observer | Settlements and immutable opinions; `self_learning_outcomes_v2`, observer events/status | 52/52 cohort outcomes schema v2; supervisor healthy, zero failures. Research/measurement only; no validated active feedback or execution authority. |

## News findings

Consumed provenance includes CoinDesk, Cointelegraph, CNBC, BBC, SEC, ECB, Fed
and Kraken. Five configured sources were idle in the observed process:
Coinbase, Kraken, Reuters, Treasury and CISA. Kraken had historical consumed
records despite being idle after this startup. News/source status and `/api/realtime/status`
already reported warnings before this change. Runtime source scheduling uses a
shared cycle; it does not meet the legacy specification's independent per-agent
due-cycle contract. The live route describes source agents, while the legacy
`news_monitor.agent_network` is not the Council's injected news reader.

`SourceAgent._analyze` produces an unsigned relevance/reliability/urgency score
and a separate `bullish`/`bearish`/`neutral` label. `_news_opinion` recognizes
`bullish` but omits `bearish` from its negative labels; positive score magnitude
also makes neutral rows bullish. Earlier consumed labels included 1,529 neutral
and 266 bearish rows; recent labels included 1,494 neutral and 228 bearish rows.
Nevertheless, most source-group votes were BUY: 157/173 earlier and 71/79 recent.

The DB adapter uses storage time as `created_at`, not publication time. The
captured consumed rows included 90 earlier and 152 recent publication ages over
six hours. No future source rows were observed, but the provider lacks an upper
time bound and the lineage collector reports future rows without vetoing them.
Missing publication timestamps are fabricated as collection time by `_article`.

Article-ID deduplication exists, but its identity includes title/publication time.
Changed versions of the same URL can become separate IDs; the same articles
also appear in overlapping news groups. Mean vote-input counts versus unique
URL hashes were 56.8/17.1 earlier and 113.4/39.0 recent. Syndication independence
and per-symbol relevance are explicitly unestablished. Lineage is persisted
beside each decision, but its status does not validate or deduplicate the vote.

A bounded decision-only ablation reproduced all 57 stored GC results from
persisted opinions. Removing news opinions made all 57 WAIT. News therefore
measurably gates and influences direction, but these votes do not establish
independent alpha. News polarity, freshness and vote independence remain
follow-up defects; changing their weights in this correction would confound it.

## Costs, exits and learning limitations

PAPER debits 0.1% per fill, uses BBO plus 2bps base slippage and modeled impact,
and rounds price/quantity to dynamically fetched rules. Impact is included in
slippage, not charged twice. The 52 pairs reconcile to within 1e-8 USDT. The
0.1% is a model assumption, consistent with Bybit's published ordinary spot
schedule, not a verified private account tier; regional/VIP rates differ.
[Bybit fee structure](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure).

Impact uses quantity divided by 24h turnover-derived base volume, not immediate
orderbook depth. Future impact remains uncertain. Stops at -1.5% and TP at +3%
use quote movement from entry fill; final BBO/slippage/fees explain why realized
losses can exceed the nominal stop. No stop/TP optimization was performed.

Learning chronology now uses settlement availability, normalizes DQ probability
confidence to percentage at the typed boundary, and leaves V2 profit/loss
outcomes economically labeled rather than inventing opposite-direction truth.
The observer only joins earlier reconciled outcomes and explicit policy epochs;
equivalence records are append-only and cannot backdate support. These are
measurement safeguards, not an active learned policy. No challenger/validated
lesson was found affecting the active V2 decision. Old broad learning summaries
mix policies and historical book sizes and are unsuitable as this cohort's edge.

## Delivery and prospective gate

Use the canonical `deploy/vps/update_from_main.sh` at the exact merged SHA.
It retains the previous image, validates PAPER locks, backs up the canonical
database, preserves the existing data volume/proxy network and automatically
rolls back failed startup. For later verification failure, use the existing
exact-SHA rollback with the retained image; never overwrite the live database.
Deployment results belong to the canonical change ledger and runtime evidence.

Historical profitability is **not proven**. After validated prospective support
exists, a distinct candidate must produce at least 50 NEW closes over at least
7 calendar days, wins > losses, net after costs > 0, expectancy > 0, PF >= 1.20,
portfolio max drawdown <= 5%, no safety/accounting/lookahead violations, and
results not dependent on one abnormal winner. Carry-in and prior-policy trades
cannot count toward that gate. The present containment alone cannot pass it.
