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

## API

Standalone:

```powershell
python -m uvicorn learning.bot_communication_app:app --reload
```

Main dashboard:

```powershell
python -m uvicorn dashboard.app:app --reload
```

Endpoints:

```text
GET  /api/bot-network/health
GET  /api/bot-network/matrix
POST /api/bot-network/messages
POST /api/bot-network/broadcast
POST /api/bot-network/consensus
GET  /api/bot-network/inbox/{bot_name}
GET  /api/bot-network/outbox/{bot_name}
GET  /api/bot-network/threads/{thread_id}
POST /api/bot-network/messages/{message_id}/read
GET  /bot-network
```

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

Endpoint:

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

Endpoint:

```text
POST /api/bot-network/messages
```

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
launch check integration
```

## Итог

Теперь боты могут не просто существовать рядом, а обмениваться задачами и ответами.

Это основа для:

```text
multi-agent debate
consensus-based decision
risk/legal escalation
learning rule broadcast
incident response
owner command routing
```
