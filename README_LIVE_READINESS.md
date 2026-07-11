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

## Power-loss resilience

- Windows durable root defaults to `D:\SharipovAI\data`.
- State is checkpointed every 10 seconds.
- Critical execution events remain persisted immediately.
- Every valid JSON state receives a `.lastgood` copy.
- Checkpoints use flush and `fsync` before atomic replacement.
- Startup validates primary state and restores the last-known-good copy when the primary file was damaged by abrupt power loss.
- Shutdown creates a final checkpoint when the operating system provides a normal shutdown event.
- Missing, invalid or unrecoverable execution evidence keeps live execution blocked.

No software-only checkpoint can guarantee preservation of data still inside the operating-system or drive hardware cache at the exact instant electricity disappears. A UPS and a drive with reliable power-loss protection remain strongly recommended before live-money activation.

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

The testnet stage must demonstrate stable execution, order reconciliation, restart recovery, forced-power-loss recovery, fee accounting and acceptable drawdown. Live flags must not be enabled merely because the code path exists.
