# SharipovAI — каноническая архитектура криптоторговли

Дата фиксации: 11 июля 2026 года.

Этот документ является единым проектным источником для всех чатов, Codex-задач и будущих изменений, связанных с криптовалютами, Bybit, рыночными данными и торговыми решениями.

## 1. Главный принцип

В SharipovAI нельзя создавать отдельный новый ИИ только потому, что появилась новая торговая функция. Сначала функция добавляется существующему владельцу из `ai_architecture_registry.py`.

Официальный навык `skills/bybit-trading/SKILL.md` — это транспортный и протокольный слой Bybit. Он не заменяет General Controller, Market Intelligence, Risk Engine, Portfolio Engine, Decision Quality, Learning Engine или Security Guard и не имеет права самостоятельно принимать окончательное решение о реальной сделке.

## 2. Владельцы торговых обязанностей

### `general_controller`

Управляет последовательностью работы органов, проверяет зависимости, свежесть данных, здоровье сервисов и возможность продолжения процесса. Не рассчитывает торговый сигнал самостоятельно.

### `market_intelligence`

Единственный владелец рыночных данных и рыночного анализа:

- Bybit REST и WebSocket котировки;
- стакан, bid/ask, spread и глубина;
- свечи, объём, open interest и funding;
- технические признаки и режим рынка;
- межбиржевой контроль Bybit, Binance, OKX, Kraken и Coinbase;
- обнаружение stale, anomalous и inconsistent data.

Внутренние специализации, а не новые верхнеуровневые ИИ:

- `market_data_adapter` — нормализация API и WebSocket;
- `microstructure_analyzer` — spread, depth, imbalance, liquidity и slippage;
- `regime_analyzer` — trend/range/high-volatility/illiquid;
- `technical_signal_analyzer` — признаки и кандидаты, но не разрешение сделки.

### `news_intelligence`

Владеет новостными событиями и их влиянием на рынок. Существующий `crypto_ai` остаётся дочерним специализированным агентом сети News AI.

Внутренние специализации:

- проверка источника и времени публикации;
- классификация события;
- связывание новости с активами;
- измерение подтверждённой реакции рынка;
- отделение факта от предположения.

### `risk_engine`

Единственный орган, который имеет право блокировать сделку по риску:

- максимальный размер позиции и notional;
- риск на сделку и дневной риск;
- drawdown и loss streak;
- leverage и liquidation distance;
- concentration и correlated exposure;
- stale-data, volatility и liquidity limits;
- stress scenarios;
- emergency kill switch recommendation.

Stress Lab является подмодулем Risk Engine, а не отдельным ИИ.

### `portfolio_engine`

Единственный владелец капитала и учёта:

- cash, equity и available balance;
- позиции и средняя цена;
- realized/unrealized PnL;
- комиссии, funding и ожидаемое проскальзывание;
- суммарная и коррелированная экспозиция;
- отчёты, allocation и rebalancing recommendations.

Exchange Cost AI должен быть функцией Portfolio Engine, а не отдельным верхнеуровневым органом.

### `virtual_execution`

Исполняет только virtual/paper операции и хранит их жизненный цикл. Testnet bridge может зеркалировать только новые подтверждённые virtual-сделки после прохождения всех защитных ворот.

### `decision_quality`

Объединяет Confidence Engine, Consensus Engine и Trade Gate:

- собирает структурированные результаты органов;
- выявляет противоречия;
- рассчитывает итоговую уверенность;
- требует достаточное количество независимых подтверждений;
- возвращает `ALLOW`, `WAIT` или `BLOCK`;
- не может отменить блокировку Risk Engine или Security Guard.

Trade Gate — процесс принятия решения, а не отдельный новый ИИ.

### `learning_engine`

Учится только на сохранённых Evidence:

- virtual/testnet/live outcomes;
- ошибки прогнозов;
- комиссии, slippage и funding;
- ложные сигналы и пропущенные сделки;
- market-regime context;
- новости и подтверждённая реакция рынка.

Learning Engine может предлагать изменение правил, но не применять торговое правило напрямую без тестов, сравнения и одобрения General Controller.

### `security_guard`

Имеет безусловное право блокировки:

- секреты и API permissions;
- доступ к данным личного аккаунта;
- mainnet execution;
- withdrawal/transfer permissions;
- replay и duplicate order protection;
- manual confirmation и kill switch.

Bybit API-ключ для ИИ не должен иметь Withdraw permission. Предпочтителен отдельный AI/standard subaccount с ограниченным балансом и лимитами.

## 3. Роль официального Bybit skill

Закреплённая версия:

- skill: `bybit-trading`;
- версия: `1.5.3`;
- upstream commit: `0a0c9a7af9cbaeb0d29f3f90498043ff4b7b5179`;
- локальные метаданные: `skills/bybit-trading/SOURCE.json`.

Навык используется для:

- выбора правильного Bybit V5 endpoint;
- формирования и подписи запросов;
- REST/WebSocket форматов;
- проверки параметров инструмента;
- получения market/account/order/position данных;
- testnet/mainnet environment routing;
- structured operation confirmation.

Навык не используется как источник торгового преимущества и не должен самостоятельно выбирать направление, leverage или размер капитала.

## 4. Канонический поток решения

1. `market_intelligence` получает свежие данные и сохраняет источник, exchange timestamp и receive timestamp.
2. `news_intelligence` добавляет только подтверждённые релевантные события.
3. `portfolio_engine` рассчитывает фактический капитал, текущую экспозицию и полную стоимость операции.
4. `risk_engine` рассчитывает лимиты и возможные причины блокировки.
5. `decision_quality` сравнивает независимые выводы и формирует решение.
6. `general_controller` проверяет здоровье всей цепочки и отсутствие пропущенных владельцев.
7. `security_guard` выполняет последний обязательный контроль.
8. `virtual_execution` исполняет paper-операцию либо guarded executor отправляет testnet-заявку.
9. Результаты и последующее движение цены сохраняются в Evidence для `learning_engine`.

Ни один LLM-ответ не должен напрямую вызывать endpoint создания ордера.

## 5. Структурированный контракт между органами

Каждый торговый кандидат должен содержать минимум:

```json
{
  "candidate_id": "unique-id",
  "symbol": "BTCUSDT",
  "category": "spot|linear",
  "side": "Buy|Sell",
  "environment": "paper|testnet|mainnet",
  "market_timestamp_ms": 0,
  "received_timestamp_ms": 0,
  "reference_price": 0,
  "data_sources": [],
  "market_regime": "trend|range|high_volatility|illiquid|unknown",
  "signal_evidence": [],
  "news_evidence": [],
  "portfolio_snapshot_id": "",
  "estimated_fees": 0,
  "estimated_slippage": 0,
  "risk_score": 0,
  "risk_blocks": [],
  "confidence": 0,
  "consensus": 0,
  "decision": "ALLOW|WAIT|BLOCK",
  "expires_at_ms": 0
}
```

Отсутствующее обязательное поле означает `BLOCK`, а не попытку догадаться.

## 6. Исполнение и подтверждение

Для любой отправки ордера обязательно:

- получать актуальные `tickSize`, `qtyStep`, minimum notional и лимиты через instruments-info;
- использовать уникальный `orderLinkId`;
- проверять свежесть WebSocket-котировки;
- рассчитывать worst-case fee и slippage;
- повторно проверять Risk Engine непосредственно перед отправкой;
- считать REST-ответ только подтверждением принятия запроса, а окончательный статус подтверждать private WebSocket/order query;
- сохранять accepted, rejected, filled, partially-filled, cancelled и error события;
- не повторять заявку после timeout, пока не проверены `orderLinkId` и текущий статус.

## 7. Этапы допуска

### Этап A — Read-only

Разрешены market data и чтение личного Bybit account snapshot. Никаких write endpoints.

### Этап B — Virtual/Paper

Автономные виртуальные сделки с реальными рыночными данными, комиссиями, funding, slippage и persistent state.

### Этап C — Testnet

Только после достаточного Evidence, свежих данных, включённых отдельных flags и лимита notional. Исторические paper-сделки не воспроизводятся автоматически.

### Этап D — Ограниченный Mainnet

Остаётся выключенным, пока одновременно не выполнены:

- успешный полный CI;
- стабильный Render runtime;
- достаточная testnet-история;
- ограниченный subaccount;
- запрет Withdraw;
- ручной unlock владельца;
- отдельное точное подтверждение операции;
- выключенный kill switch;
- жёсткий дневной лимит и максимальный notional.

### Этап E — Масштабирование

Размер капитала может только рекомендоваться на основании статистики. Автоматическое увеличение капитала запрещено.

## 8. Текущее состояние проекта

Уже существует и не должно дублироваться:

- real Bybit/Binance public quotes;
- основной Bybit WebSocket market stream;
- автономный Virtual Account;
- guarded testnet/live execution code;
- StageController;
- persistent execution journal;
- read-only personal Bybit account sync;
- official Bybit trading skill;
- межбиржевой watchdog в отдельном открытом PR;
- Crypto News AI внутри сети из 13 News AI;
- General Controller, Risk Engine, Portfolio Engine, Decision Quality, Learning Engine и Security Guard.

Открытые обязательные работы:

1. Проверить исправление FastAPI lifecycle полным CI и production smoke test.
2. Завершить защиту `/api/exchange/account/status`, `/snapshot`, `/sync` и объединить её только после зелёных тестов.
3. Не объединять low-latency live PR до разрешения конфликтов, полного CI, testnet evidence и recovery tests.
4. Добавить системный `trading_candidate` contract и schema validation.
5. Добавить отдельный pre-trade cost/risk snapshot с неизменяемым evidence ID.
6. Добавить подтверждение order state через private WebSocket.
7. Добавить reconciliation после restart: account, positions, open orders и execution journal.
8. Добавить метрики качества по market regime, а не только общий win rate.
9. Добавить тесты disconnect, duplicate delivery, out-of-order WebSocket, partial fill, timeout и restart.

## 9. Обязательные проверки после изменений

Минимально:

```bash
python -m pytest
python -m compileall .
python -c "import dashboard; print(dashboard.app.title)"
```

Дополнительно для торгового контура:

- unit tests нормализации symbol/price/qty;
- stale/anomaly/consensus блокировки;
- kill switch и manual confirmation;
- duplicate `orderLinkId`;
- partial fill и asynchronous confirmation;
- persistence/restart/reconciliation;
- rate-limit/backoff;
- отсутствие секретов в логах и API;
- проверка, что Mainnet write остаётся выключенным.

После Render deploy проверяются реальные endpoints и время свежести данных. Demo/synthetic fallback запрещён.

## 10. Правило для всех чатов проекта

Перед любым предложением нового торгового ИИ чат обязан:

1. Прочитать `AGENTS.md`.
2. Проверить `ai_architecture_registry.py`.
3. Прочитать этот документ.
4. Проверить актуальные открытые PR и текущий `main`.
5. Расширить существующего владельца вместо создания копии.
6. После изменения выполнить тесты и описать фактический результат, а не предполагаемый.
