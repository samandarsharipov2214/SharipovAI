# Paper Activity Engine

## Почему раньше было только 3 сделки

В dashboard старый demo state использовал статичный список:

```text
_demo_trades() -> ровно 3 demo-сделки
```

Это не был активный paper-trading цикл.

Также `trading_intelligence.trade_gate` намеренно не размещает ордера и держит LIVE locked.

## Почему за ночь сделки не добавились

Причина была в связке:

```text
Mini App -> /api/demo/state -> _demo_trades() -> ровно 3 статичные сделки
```

Новый `Paper Activity Engine` уже был добавлен, но экран Mini App “Сделки” его не читал. Поэтому ночью ничего не менялось на экране.

## Что исправлено

Файлы:

```text
paper_activity_engine.py
paper_activity_autorun.py
dashboard/paper_activity_api.py
dashboard/static/mini-app-live.js
dashboard/templates/index.html
```

Теперь:

```text
1. Paper engine умеет catch_up после сна сервера/ночи.
2. Dashboard запускает background autorun loop при startup.
3. /api/paper-activity/state делает безопасный catch_up.
4. Mini App “Сделки” читает /api/paper-activity/state.
5. UI показывает last_reason, last tick age и autorun status.
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
PAPER_ACTIVITY_AUTORUN_ENABLED=1
PAPER_ACTIVITY_TICK_SECONDS=60
PAPER_ACTIVITY_MAX_OPEN=5
PAPER_ACTIVITY_MAX_CATCH_UP_TICKS=24
```

Минимальный tick interval — 5 секунд.

## API

```text
GET  /api/paper-activity/state
POST /api/paper-activity/tick
POST /api/paper-activity/catch-up
POST /api/paper-activity/reset
GET  /paper-activity
```

Принудительный tick:

```json
{
  "force": true
}
```

Catch-up после ночи:

```json
{
  "max_ticks": 24
}
```

## Почему он может ждать

В state смотреть:

```text
state.summary.last_reason
state.summary.last_tick_age_seconds
autorun.thread_alive
autorun.status
```

Возможные причины:

```text
not_started
waiting_interval:Ns_left
opened_paper_trade
max_open_reached_closed_oldest
catch_up_completed:N_ticks
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

Чтобы догнать ночь:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/paper-activity/catch-up -ContentType 'application/json' -Body '{"max_ticks":24}'
```
