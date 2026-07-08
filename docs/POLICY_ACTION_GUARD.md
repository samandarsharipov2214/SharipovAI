# Policy Action Guard

Policy Action Guard превращает advice от Policy/Legal Monitor в реальную проверку перед действиями ботов.

## Зачем нужен

До этого General Controller мог получить:

```text
recommended_action = block_action
```

Но это было только сообщение.

Теперь перед опасным действием бот может запросить guard:

```text
можно ли выполнить это действие?
```

И получить:

```text
allow
caution
manual_review
block
reject
```

## Файлы

```text
learning/policy_action_guard.py
learning/policy_guard_app.py
learning/tests/test_policy_action_guard.py
```

## Action types

High-risk:

```text
trade
crypto_trade
stock_trade
withdrawal
user_access
data_export
```

Medium-risk:

```text
paper_trade
bot_learning
portfolio_rebalance
news_publish
```

Safe:

```text
read_dashboard
health_check
paper_report
learning_summary
```

## Правила

Если latest advice:

```text
block_action
```

и action high-risk, результат:

```text
block
allowed = false
must_notify_owner = true
```

Если latest advice:

```text
manual_review
```

и action high-risk, результат:

```text
manual_review
allowed = false
```

Если latest advice:

```text
caution
```

и action high/medium-risk, результат:

```text
caution
allowed = true
```

Safe actions разрешаются даже при block_action.

## API

Запуск:

```powershell
python -m uvicorn learning.policy_guard_app:app --reload
```

Endpoints:

```text
POST /api/policy-guard/check
POST /api/policy-guard/check-batch
```

## Пример

```json
{
  "latest_advice": {
    "recommended_action": "block_action",
    "must_notify_owner": true
  },
  "action": {
    "action_type": "crypto_trade",
    "actor": "market_agent",
    "topic": "crypto_regulation"
  }
}
```

Ответ:

```json
{
  "decision": "block",
  "allowed": false,
  "reason": "policy_block_action"
}
```

## Проверка

```powershell
python -m pytest learning/tests/test_policy_action_guard.py
```

Тесты проверяют:

```text
block_action blocks crypto_trade
manual_review pauses withdrawal
caution allows with risk mark
safe action remains allowed
batch uses strictest decision
API check works
API batch works
```

## Следующий шаг

Guard пока отдельный API/модуль.

Следующий крупный шаг:

```text
встроить guard в dashboard/app.py перед торговыми API
встроить guard в paper trading bot
встроить guard в user/admin sensitive actions
сделать audit log для blocked actions
```
