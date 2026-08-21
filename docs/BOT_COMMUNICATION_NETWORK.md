# AI Bot Communication Network

SharipovAI получил слой связи между 11 AI-ботами.

## Зачем нужно

Раньше боты существовали как роли и отдельные блоки логики.

Теперь у них есть общий message bus:

```text
bot -> message -> inbox -> thread -> reply -> consensus
```

Это нужно, чтобы:

```text
General Controller задавал вопросы другим ботам
Risk Engine мог блокировать решения
News Agent мог отправлять срочные новости
Learning Engine мог рассылать новые правила
Consensus Engine мог собирать мнения
Security Guard мог отправлять policy/legal alert
```

## Файлы

```text
learning/bot_communication.py
learning/bot_communication_app.py
dashboard/bot_communication_api.py
learning/tests/test_bot_communication.py
dashboard/tests/test_bot_communication_dashboard_integration.py
```

## Runtime DB

```text
data/bot_communication.sqlite3
```

или env:

```text
BOT_COMMUNICATION_DB
```

## Боты

```text
general_controller
market_agent
news_agent
risk_engine
portfolio_engine
paper_trading_bot
confidence_engine
consensus_engine
stress_bot
learning_engine
security_guard
```

## Message types

```text
status_update
question
answer
risk_alert
legal_alert
learning_update
consensus_request
consensus_response
handoff
command
```

## API ownership

### Канонический dashboard — единственный control plane

Все управляющие и изменяющие состояние операции Bot Network принадлежат основному dashboard-приложению:

```powershell
python -m uvicorn dashboard.app:app --reload
```

Канонические mutation endpoints требуют authenticated admin, same-origin проверку для cookie-authenticated запросов и сохраняют server-derived actor provenance:

```text
POST /api/bot-network/messages
POST /api/bot-network/broadcast
POST /api/bot-network/consensus
POST /api/bot-network/chat                  # privileged pause/self-check/learn требуют admin
POST /api/bot-network/agent/{bot_name}/self-check
POST /api/bot-network/agent/{bot_name}/pause
POST /api/bot-network/agent/{bot_name}/learn
```

Read endpoints dashboard:

```text
GET /api/bot-network/health
GET /api/bot-network/matrix
GET /api/bot-network/inbox/{bot_name}
GET /api/bot-network/outbox/{bot_name}
GET /api/bot-network/threads/{thread_id}
GET /bot-network
```

### Standalone — только read-only compatibility service

Standalone можно запускать для health/read диагностики:

```powershell
python -m uvicorn learning.bot_communication_app:app --reload
```

Он не является control plane. Доступны только read endpoints:

```text
GET /api/bot-network/health
GET /api/bot-network/matrix
GET /api/bot-network/inbox/{bot_name}
GET /api/bot-network/outbox/{bot_name}
GET /api/bot-network/threads/{thread_id}
GET /bot-network
```

Старые standalone mutation endpoints намеренно retired и возвращают HTTP 410:

```text
POST /api/bot-network/messages
POST /api/bot-network/broadcast
POST /api/bot-network/consensus
POST /api/bot-network/messages/{message_id}/read
```

Не переносите клиентов на отдельный standalone mutation API: для изменений используйте только канонический dashboard API. Отдельного dashboard endpoint для `mark-read` сейчас нет; вызывающий код не должен предполагать его наличие.

## Проверка связи всех ботов

```text
GET /api/bot-network/health
```

Нужно увидеть:

```json
{
  "full_mesh_possible": true,
  "bot_count": 11
}
```

## Consensus request

```json
{
  "topic": "trade",
  "question": "Can we allow paper trade?",
  "participants": ["market_agent", "news_agent", "risk_engine"]
}
```

Канонический endpoint:

```text
POST /api/bot-network/consensus
```

По умолчанию Consensus Engine спрашивает:

```text
market_agent
news_agent
risk_engine
portfolio_engine
confidence_engine
```

## Пример сообщения

```json
{
  "sender": "general_controller",
  "recipient": "risk_engine",
  "message_type": "question",
  "topic": "risk",
  "priority": "high",
  "payload": {
    "question": "Can we trade?"
  }
}
```

Канонический endpoint:

```text
POST /api/bot-network/messages
```

`requested_by` не является доверенным клиентским полем: dashboard перезаписывает provenance аутентифицированным администратором.

## Launch Check

Bot Network добавлен в:

```text
/api/launch-check
/launch-check
```

Launch Check проверяет, что:

```text
bot_count = 11
full_mesh_possible = true
```

## Тесты

```powershell
python -m pytest learning/tests/test_bot_communication.py
python -m pytest dashboard/tests/test_bot_communication_dashboard_integration.py
python -m pytest tests/test_bot_network_admin_guard.py
python -m pytest
```

Тесты проверяют:

```text
full mesh matrix
send message
inbox/outbox
thread
mark read
reply
broadcast to all bots
consensus request
dashboard endpoints
standalone read-only retirement contract
admin authorization and provenance
launch check integration
```

## Итог

Bot Communication Network остаётся единым durable message bus, но управляющая authority сосредоточена в каноническом dashboard control plane. Standalone-сервис предназначен только для чтения и диагностики.
