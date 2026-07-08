# Paper Activity Engine

## Почему раньше было только 3 сделки

В dashboard старый demo state использовал статичный список:

```text
_demo_trades() -> ровно 3 demo-сделки
```

Это не был активный paper-trading цикл.

Также `trading_intelligence.trade_gate` намеренно не размещает ордера и держит LIVE locked.

## Что добавлено

Файл:

```text
paper_activity_engine.py
```

Dashboard API:

```text
dashboard/paper_activity_api.py
```

Launch Check integration:

```text
dashboard/launch_check_api.py
```

## Что умеет

```text
активный paper tick
открывать paper-сделку
ждать интервал
закрывать старую позицию при лимите open positions
объяснять last_reason
хранить state в JSON
не трогать реальные ордера
```

## Runtime state

```text
data/paper_activity_state.json
```

или env:

```text
PAPER_ACTIVITY_STATE_FILE
```

## Настройки

```text
PAPER_ACTIVITY_TICK_SECONDS=60
PAPER_ACTIVITY_MAX_OPEN=5
```

Минимальный tick interval — 5 секунд.

## API

```text
GET  /api/paper-activity/state
POST /api/paper-activity/tick
POST /api/paper-activity/reset
GET  /paper-activity
```

Принудительный tick:

```json
{
  "force": true
}
```

## Почему он может ждать

В state смотреть:

```text
summary.last_reason
```

Возможные причины:

```text
not_started
waiting_interval:Ns_left
opened_paper_trade
max_open_reached_closed_oldest
trade_gate_blocked_demo
```

## Безопасность

Это PAPER/SIMULATION only.

```text
live_execution_enabled = false
real_orders_blocked = true
```

Один tick делает одно действие:

```text
или открывает сделку
или закрывает старую при max open
или ждёт интервал
или блокируется trade_gate
```

Это сделано специально, чтобы бот не плодил сделки без контроля.

## Проверка

```powershell
python -m pytest tests/test_paper_activity_engine.py
python -m pytest dashboard/tests/test_paper_activity_dashboard.py
python -m pytest
```

## Как пользоваться

После запуска dashboard:

```powershell
python -m uvicorn dashboard.app:app --reload
```

Открыть:

```text
/paper-activity
/api/paper-activity/state
```

Чтобы сразу заставить paper engine действовать:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/paper-activity/tick -ContentType 'application/json' -Body '{"force":true}'
```
