# SharipovAI live execution readiness

Real-money execution remains disabled by default. The project is prepared so a live order is fail-closed unless every required gate passes immediately before submission.

## Market-data timing

- Primary trading price: continuous Bybit WebSocket stream.
- Maximum accepted WebSocket quote age: 1 second.
- Cross-exchange watchdog: Bybit, Binance, OKX, Kraken, Coinbase every 2 seconds.
- Maximum accepted consensus age: 2.5 seconds.
- Minimum agreeing exchanges: 3.
- Maximum exchange deviation: 0.35%.
- Maximum reference-price slippage: 0.20%.

The 5-second paper loop is not a live execution clock. It remains a strategy-testing cadence only.

## Mandatory live gates

- explicit live mode;
- API credentials;
- owner manual unlock;
- exact risk confirmation string;
- kill switch disabled;
- order notional below the configured cap;
- fresh verified WebSocket price;
- fresh cross-exchange consensus;
- bounded exchange deviation;
- bounded reference-price slippage;
- unique client order ID for idempotency.

Missing or malformed evidence blocks the order. Synthetic prices are never used.

## Before first real-money activation

The testnet stage must still demonstrate stable execution, order reconciliation, restart recovery, fee accounting and acceptable drawdown. Live flags must not be enabled merely because the code path exists.
