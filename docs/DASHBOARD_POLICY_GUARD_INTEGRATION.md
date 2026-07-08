# Dashboard Policy Guard Integration

Policy Action Guard встроен в реальные dashboard endpoints.

Теперь `block_action` от Policy/Legal Monitor не просто показывается в журнале, а может остановить опасные действия до выполнения handler.

## Что добавлено

Файлы:

```text
dashboard/policy_guard.py
dashboard/policy_guard_middleware.py
dashboard/tests/test_policy_guard_dashboard_integration.py
```

Изменены:

```text
dashboard/app.py
dashboard/trading_intelligence_api.py
```

## Защищённые endpoints

Middleware защищает:

```text
GET  /api/run
GET  /api/trade-gate
POST /api/trade-gate
POST /api/learning-v2/propose
```

## Как работает

```text
Policy Monitor создаёт legal/policy alert
↓
Policy Journal сохраняет latest controller advice
↓
Dashboard Policy Guard читает latest advice
↓
перед risky endpoint выполняется проверка
↓
если block_action/manual_review — endpoint возвращает 403
↓
handler не выполняется
```

## Ответ при блокировке

```json
{
  "status": "blocked",
  "error": "policy_guard_blocked",
  "decision": "block",
  "reason": "policy_block_action",
  "action_type": "trade",
  "recommended_action": "block_action",
  "must_notify_owner": true
}
```

## Почему защищён /api/run

`/api/run` запускает основной runner. Даже если сейчас система работает в demo/sandbox режиме, этот endpoint считается risky, потому что в будущем runner может быть связан с реальными действиями.

Поэтому при критическом юридическом риске он блокируется до выполнения runner.

## Что остаётся разрешённым

Safe endpoints не блокируются:

```text
/api/health
/health
read_dashboard
learning_summary
paper_report
```

Так система не запирает сама себя и остаётся доступной для диагностики.

## Runtime dependency

Guard читает latest advice из:

```text
data/policy_journal.json
```

Или из пути:

```text
POLICY_JOURNAL_FILE
```

## Проверка

```powershell
python -m pytest dashboard/tests/test_policy_guard_dashboard_integration.py
```

Тесты проверяют:

```text
block_action блокирует /api/run
runner не выполняется при блокировке
block_action блокирует /api/trade-gate
/api/health остаётся доступен
continue разрешает /api/run
```

## Следующий шаг

```text
1. Встроить guard в user/admin sensitive actions.
2. Добавить audit log для blocked actions в единый security journal.
3. Добавить визуальный статус Policy Guard в dashboard.
4. Создать unified secure entrypoint, где auth + policy guard + legal monitor dashboard работают вместе.
```
