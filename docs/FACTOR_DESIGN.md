# SharipovAI Factor Design

## Purpose

This document defines the scoring factor architecture for SharipovAI. It describes the planned factors used to evaluate market conditions, asset behavior, risk context, and portfolio exposure.

The document is intended as a product and engineering reference. It does not define trading execution rules and does not constitute investment advice.

## Scoring Architecture

SharipovAI factor scoring is designed as a modular system. Each factor evaluates one measurable dimension of the market and returns a normalized score that can be combined with other factor scores through defined weights.

The architecture is intended to support:

- Transparent factor definitions
- Market-relative scoring
- Clear data source ownership
- Independent factor evolution
- Auditable scoring output
- Future expansion into additional market, macro, social, and portfolio inputs

## Factor Table

| Factor | Description | Weight | Data source | Current status | Future improvements |
| --- | --- | --- | --- | --- | --- |
| Market Trend | Measures the directional behavior of an asset or market over a defined period. | TBD | Market price data | Planned | Add multi-timeframe trend analysis and benchmark-relative trend scoring. |
| Volume | Evaluates trading activity using 24h volume and related market participation metrics. | TBD | Exchange ticker data | Partially implemented | Add market-relative volume normalization across exchanges and time windows. |
| Liquidity | Measures how easily an asset can be traded using turnover, spread, and available market depth. | TBD | Exchange ticker data, order book data | Partially implemented | Add depth-weighted liquidity and slippage estimation. |
| Volatility | Measures the size of price movement over a defined period. | TBD | Market price data | Partially implemented | Add realized volatility, intraday ranges, and volatility regime detection. |
| Momentum | Measures the strength and persistence of recent price movement. | TBD | Market price data | Planned | Add momentum decay, multi-period confirmation, and reversal detection. |
| News | Evaluates relevant news flow and event impact. | TBD | News providers, RSS feeds, trusted publications | Planned | Add source credibility scoring and event classification. |
| Social Sentiment | Measures public discussion tone and intensity across social platforms. | TBD | Social media APIs, community platforms | Planned | Add spam filtering, language detection, and influence-weighted sentiment. |
| Fear & Greed | Measures broad market emotional conditions. | TBD | Market sentiment indices, derived market indicators | Planned | Add custom fear and greed model using volatility, volume, dominance, and sentiment inputs. |
| Order Book | Evaluates supply and demand structure from bid and ask depth. | TBD | Exchange order book data | Planned | Add imbalance scoring, depth clustering, and liquidity wall detection. |
| Funding Rate | Measures derivatives market positioning pressure through funding payments. | TBD | Exchange derivatives data | Planned | Add cross-exchange funding comparison and funding divergence detection. |
| Open Interest | Measures derivatives market participation and leverage buildup. | TBD | Exchange derivatives data | Planned | Add open interest change rate, price-open interest divergence, and liquidation-risk context. |
| Whale Activity | Tracks large-holder or large-transaction behavior. | TBD | On-chain analytics, exchange flow data | Planned | Add large transfer classification and exchange inflow/outflow alerts. |
| On-chain Activity | Measures blockchain network activity and asset usage. | TBD | On-chain data providers, blockchain nodes | Planned | Add active addresses, transaction volume, fees, and network growth scoring. |
| Bitcoin Dominance | Measures Bitcoin market share relative to the broader crypto market. | TBD | Market capitalization data | Planned | Add dominance trend scoring and altcoin rotation context. |
| Correlation | Measures relationship between assets, sectors, or market benchmarks. | TBD | Historical market data | Planned | Add rolling correlation, regime changes, and diversification impact scoring. |
| Macro Economy | Evaluates broad economic conditions that may affect markets. | TBD | Economic data providers, central bank data, government statistics | Planned | Add inflation, interest rate, employment, liquidity, and policy factor models. |
| Risk | Measures downside exposure, instability, and adverse market conditions. | TBD | Market data, volatility data, portfolio data | Planned | Add drawdown, value-at-risk, stress testing, and scenario analysis. |
| Portfolio Exposure | Measures current allocation, concentration, and asset-level exposure. | TBD | Portfolio records, account data, internal position data | Planned | Add exposure limits, concentration scoring, and portfolio-level risk contribution. |

## Status Notes

Factors marked as partially implemented have an initial deterministic implementation in the analysis layer. Factors marked as planned require additional data integrations, validation, and scoring design before production use.

## Governance

All factor definitions, weights, and scoring formulas should be reviewed before being used in production workflows. Changes to factor behavior should be documented, versioned, and tested against representative market data.
