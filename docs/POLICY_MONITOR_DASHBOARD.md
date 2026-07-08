# Policy Monitor Dashboard & Ops

Этот слой объединяет юридический мониторинг, журнал alerts, совет General Controller и dashboard.

## Файлы

```text
learning/policy_journal.py
learning/policy_ops.py
learning/policy_dashboard_app.py
learning/tests/test_policy_monitor_ops.py
```

## Что реализовано

```text
1. Журнал policy/legal alerts.
2. Дедупликация alerts в журнале.
3. Сохранение latest controller advice.
4. Operations runner: monitor cycle -> journal -> snapshot.
5. Dashboard page для просмотра alerts.
6. API для запуска и snapshot.
```

## Запуск

```powershell
python -m uvicorn learning.policy_dashboard_app:app --reload
```

## Страница

```text
/policy-monitor
```

Показывает:

```text
последний совет главному ИИ
recommended_action
must_notify_owner
журнал alerts
severity
topic
title
source
action
affected bots
```

## API

```text
POST /api/policy-monitor/run
GET  /api/policy-monitor/snapshot
```

## Runtime files

```text
data/legal_watch_state.json
data/policy_journal.json
```

Можно переопределить:

```text
LEGAL_WATCH_STATE_FILE
POLICY_JOURNAL_FILE
```

## Как запускать ежедневно

Scheduler-helper в код добавить не удалось из-за блокировки GitHub-коннектора. Поэтому запускать можно внешним планировщиком:

### Cron / Linux

```bash
0 8 * * * curl -X POST http://127.0.0.1:8000/api/policy-monitor/run -H 'Content-Type: application/json' -d '{"items":[]}'
```

### Windows Task Scheduler

Команда:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/policy-monitor/run -ContentType 'application/json' -Body '{"items":[]}'
```

### GitHub Actions / server job

Можно запускать endpoint по расписанию, когда приложение доступно на сервере.

## Проверка

```powershell
python -m pytest learning/tests/test_policy_monitor_ops.py
```

Тесты проверяют:

```text
journal stores alerts
journal deduplicates alerts
latest advice persists
ops runner persists cycle results
dashboard API works
dashboard page renders alert
```
