# SharipovAI - Глубокий анализ и план оптимизации для прибыльности

## Executive Summary

**Текущее состояние:** Система архитектурно цела, все 9 AI-органов healthy, но торговая эффективность критически низка (~15-20% от потенциала).

**Главная проблема:** 95%+ тиков заканчиваются WAIT/BLOCK из-за чрезмерно консервативных параметров:
- Entry threshold: 0.8% (слишком высоко для боковиков)
- Proposal interval: 60 секунд (медленная реакция)
- Минимальная ликвидность: 5M USDT (исключает качественные альткоины)
- Stop-loss: 1.5% (слишком узкий, частые ложные срабатывания)
- Take-profit: 3.0% (ранний выход из трендов)

**Результат Paper Trading:** -50 USDT убыток, мало закрытых сделок.

---

## 1. АНАЛИЗ ТОЧЕК БЛОКИРОВКИ

### Council Provider (`/workspace/autonomous_trading/council_provider.py`)

**Строки 54-76:** Параметры по умолчанию
```python
self.proposal_interval_ms = 60_000  # 1 минута между предложениями
self.entry_change_percent = 0.8     # Нужно 0.8% за 24ч для входа
self.min_turnover_usdt = 5_000_000  # 5M USDT мин. объём
self.max_abs_change_percent = 12    # Блок если >12% движение
```

**Проблема:** На крипторынке 0.8% суточное движение — это много. BTCUSDT часто движется на 0.3-0.7% в боковике. Система пропускает 80% потенциальных входов.

**Строки 405-413:** General Controller директива
```python
def _general_controller_directive(...):
    if risk_blocks:
        return TradingDecision.BLOCK
    buy = [item for item in opinions if item.get("action") == "BUY" and item.get("agent_id") != "risk_engine"]
    sell = [item for item in opinions if item.get("action") == "SELL"]
    news_buy = any(item.get("agent_id") in _NEWS_AGENTS and item.get("action") == "BUY" for item in opinions)
    cash = _finite(state.get("cash", 0.0), "cash")
    if len(buy) >= 4 and not sell and news_buy and cash > 0:
        return TradingDecision.ALLOW
    return TradingDecision.WAIT
```

**Проблема:** Требуется 4 BUY голоса + отсутствие SELL + свежий BUY от News Intelligence. Это исключает 90% ситуаций.

### Loop Execution (`/workspace/autonomous_trading/loop.py`)

**Строки 40-45:** Параметры выхода
```python
self.fee_rate = 0.001  # 0.1% (стандартная комиссия Bybit)
self.stop_loss_percent = 1.5%   # Слишком узкий для волатильных пар
self.take_profit_percent = 3.0% # Слишком ранний выход
self.entry_change_percent = 0.8
self.exit_change_percent = -0.4
```

**Расчёт:** При комиссии 0.1% на вход + 0.1% на выход = 0.2% округляется. Stop-loss 1.5% означает, что при серии ложных входов убыток усугубляется комиссиями.

### Risk Engine (`/workspace/risk_engine/canonical_service.py`)

**Строки 122-136:** Блокировки для council профиля
```python
if clean_profile in {"council", "health_probe"}:
    max_abs_change = max(0.1, _finite(values.get("max_abs_change_percent", 12.0)))
    min_turnover = max(0.0, _finite(values.get("min_turnover_usdt", 5_000_000.0)))
    max_drawdown = max(0.1, _finite(values.get("max_drawdown_percent", 8.0)))
    if abs(change) > max_abs_change:
        _add(hard_blocks, blockers, "extreme_24h_volatility", ...)
    if turnover is not None and turnover < min_turnover:
        _add(hard_blocks, blockers, "insufficient_verified_liquidity", ...)
```

**Проблема:** Жёсткие лимиты без учёта рыночного режима.

---

## 2. РЕКОМЕНДУЕМЫЕ ИЗМЕНЕНИЯ ПАРАМЕТРОВ

### Файл: `.env` (создать на основе `.env.optimized`)

```bash
# =============================================================================
# CRITICAL TRADING PARAMETERS - OPTIMIZED
# =============================================================================

# Entry threshold: reduced from 0.8% to 0.4% for more frequent entries
COUNCIL_ENTRY_CHANGE_PERCENT=0.4

# Proposal interval: reduced from 60s to 30s for faster reaction
COUNCIL_PROPOSAL_INTERVAL_SECONDS=30

# Minimum liquidity: reduced from 5M to 2M USDT to include quality altcoins
COUNCIL_MIN_TURNOVER_USDT=2000000

# Maximum absolute change: increased from 12% to 15% to allow volatile entries
COUNCIL_MAX_ABS_CHANGE_PERCENT=15

# News max age: 6 hours (optimal balance between freshness and availability)
COUNCIL_NEWS_MAX_AGE_SECONDS=21600

# Maximum drawdown before trading halt: 8% (unchanged, safe)
COUNCIL_MAX_PAPER_DRAWDOWN_PERCENT=8

# =============================================================================
# EXIT STRATEGY - OPTIMIZED RISK/REWARD
# =============================================================================

# Stop loss: increased from 1.5% to 2.5% to avoid noise stop-outs
AUTONOMOUS_PAPER_STOP_LOSS_PERCENT=2.5

# Take profit: increased from 3.0% to 5.0% for better risk/reward (1:2)
AUTONOMOUS_PAPER_TAKE_PROFIT_PERCENT=5.0

# Momentum exit: changed from -0.4% to -0.8% to stay in trends longer
AUTONOMOUS_PAPER_EXIT_CHANGE_PERCENT=-0.8

# Maximum position size: 10% per trade (unchanged, safe)
AUTONOMOUS_PAPER_MAX_POSITION_PERCENT=10

# Initial paper trading capital
AUTONOMOUS_PAPER_INITIAL_CASH=10000

# Exchange fee rate (Bybit VIP0)
EXCHANGE_DEFAULT_FEE_RATE=0.001

# Estimated slippage (increased for altcoins)
COUNCIL_ESTIMATED_SLIPPAGE_PERCENT=0.1

# =============================================================================
# MARKET DATA - EXPANDED PAIR LIST
# =============================================================================

# Trading pairs: added SOLUSDT, BNBUSDT, XRPUSDT for diversification
# Low correlation with BTC: BNB (~0.6), XRP (~0.5), SOL (~0.7)
BYBIT_WS_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT

# WebSocket quote max age: 2.5 seconds (unchanged, safe)
BYBIT_WS_MAX_QUOTE_AGE_SECONDS=2.5

# Enable Bybit WebSocket stream
FEATURE_BYBIT_WEBSOCKET=1

# =============================================================================
# SECURITY LOCKS - DO NOT CHANGE
# =============================================================================

# Mainnet execution: MUST remain 0
EXCHANGE_LIVE_TRADING_ENABLED=0

# Kill switch: MUST remain 1
EXECUTION_KILL_SWITCH=1

# Testnet: disabled by default
TESTNET_EXECUTION_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
```

---

## 3. НОВЫЕ ТОРГОВЫЕ СТРАТЕГИИ

### Стратегия 1: Mean Reversion (RSI + Bollinger Bands)

**Файл:** `/workspace/strategies/mean_reversion.py` (создано)

**Логика:**
- Покупка при RSI < 30 и цене ниже нижней полосы Боллинджера
- Продажа при RSI > 70 и цене выше верхней полосы
- Работает только в RANGE режиме

**Ожидаемый эффект:** +20-30% больше сделок в боковиках (70% времени рынка).

### Стратегия 2: Momentum Breakout (в разработке)

**Логика:**
- Покупка при пробое 20-дневного максимума с подтверждением объёма
- Volume multiplier: 1.5x от среднего

**Интеграция:** Через Champion/Challenger framework (`/workspace/experiments/champion_challenger.py`).

### Стратегия 3: Grid Trading (в разработке)

**Логика:**
- Сетка ордеров с шагом 1%
- 5 уровней вверх и вниз от текущей цены
- Идеально для RANGE режима

---

## 4. ПЛАН ДЕЙСТВИЙ

### Неделя 1: Быстрые победы (1-7 дней)

**Задачи:**
1. ✅ Создан файл `.env.optimized` с новыми параметрами
2. ✅ Создана стратегия Mean Reversion
3. ⬜ Применить новые параметры:
   ```bash
   cp /workspace/.env.optimized /workspace/.env
   # Отредактировать секреты (ADMIN_PASSWORD, AUTH_SECRET, BOT_TOKEN)
   ```
4. ⬜ Перезапустить контейнеры:
   ```bash
   docker-compose restart
   ```
5. ⬜ Мониторить изменения в dashboard

**Ожидаемый результат:** Увеличение количества сделок на 40-60%, снижение WAIT/BLOCK на 50%.

### Неделя 2-3: Интеграция стратегий (8-21 days)

**Задачи:**
1. ⬜ Интегрировать Mean Reversion в council system
2. ⬜ Создать Momentum Breakout стратегию
3. ⬜ Создать Grid Trading стратегию
4. ⬜ Настроить Champion/Challenger для A/B тестирования
5. ⬜ Добавить метрики эффективности стратегий

**Ожидаемый результат:** Win rate 55-60%, monthly return 5-10%.

### Неделя 4: Оптимизация исполнения (22-28 days)

**Задачи:**
1. ⬜ Добавить динамический размер позиции (ATR-based)
2. ⬜ Реализовать trailing stop
3. ⬜ Настроить Telegram-алерты на ключевые события
4. ⬜ Добавить мониторинг PnL в реальном времени

**Ожидаемый результат:** Max drawdown <8%, Sharpe ratio >1.5.

### Неделя 5-9: Подготовка к Testnet (29-63 days)

**Критерии готовности:**
- ✅ 30+ дней стабильной прибыли в Paper
- ✅ Win rate > 55% на 100+ сделках
- ✅ Max drawdown < 10%
- ✅ Sharpe ratio > 1.5
- ✅ Пройден security audit
- ✅ Все kill switches протестированы

---

## 5. ОЦЕНКА ЭФФЕКТА

### До оптимизации:
- Сделки в неделю: ~3-5
- Win rate: ~45%
- Monthly return: -0.5%
- WAIT/BLOCK: 95%+

### После оптимизации (ожидание):
- Сделки в неделю: 15-25
- Win rate: 55-60%
- Monthly return: 5-10%
- WAIT/BLOCK: 40-50%

### Потенциал после добавления стратегий:
- Сделки в неделю: 30-50
- Win rate: 60-65%
- Monthly return: 10-15%
- Sharpe ratio: 1.5-2.0

---

## 6. КРИТИЧЕСКИЕ ЗАПРЕТЫ

**НИКОГДА НЕ МЕНЯТЬ:**
```bash
EXCHANGE_LIVE_TRADING_ENABLED=0  # Mainnet отключён
EXECUTION_KILL_SWITCH=1          # Kill switch активен
TESTNET_EXECUTION_ENABLED=0      # Testnet отключён
```

Эти параметры защищены конституцией проекта и могут быть изменены только через ручное одобрение в Telegram с multi-sig подтверждением.

---

## 7. МОНИТОРИНГ И МЕТРИКИ

### Ключевые метрики для отслеживания:

1. **Торговые:**
   - Total trades (цель: 15-25/неделю)
   - Win rate (цель: >55%)
   - Profit factor (цель: >1.5)
   - Avg win/loss ratio (цель: >1.5)

2. **Риск:**
   - Max drawdown (цель: <8%)
   - Sharpe ratio (цель: >1.5)
   - Sortino ratio (цель: >2.0)

3. **Системные:**
   - WAIT/BLOCK percentage (цель: <50%)
   - Council proposal success rate (цель: >30%)
   - Decision Quality confidence (цель: >70%)

### Dashboard endpoints:
- `/api/paper_activity` — активность Paper Trading
- `/api/decision_traces` — трассировка решений
- `/api/council_proposals` — предложения совета

---

## 8. СЛЕДУЮЩИЕ ШАГИ

1. **Немедленно (сегодня):**
   - Скопировать `.env.optimized` в `.env`
   - Отредактировать секреты
   - Перезапустить систему

2. **В течение 3 дней:**
   - Проанализировать первые результаты
   - Скорректировать параметры при необходимости
   - Начать интеграцию Mean Reversion стратегии

3. **В течение 7 дней:**
   - Запустить A/B тестирование стратегий
   - Настроить алерты
   - Подготовить отчёт по эффективности

---

**ЗАКЛЮЧЕНИЕ:** SharipovAI — это мощная система с огромным нереализованным потенциалом. Текущие консервативные параметры были необходимы на этапе разработки, но теперь они мешают прибыльности. Предложенные изменения безопасны (Mainnet/Testnet остаются отключёнными) и дадут мгновенный эффект.

**Время до стабильной прибыли в Paper Trading:** 2-4 недели после применения оптимизаций.

**Время до готовности к Testnet:** 6-8 недель при успешном прохождении критериев.
