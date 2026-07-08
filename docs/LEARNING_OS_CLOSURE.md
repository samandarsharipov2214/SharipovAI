# Learning OS Closure

Этот документ фиксирует закрытие раздела самообучения SharipovAI.

## Что было проблемой

До этого самообучение было разрозненным:

```text
отдельные учебные пакеты
отдельный legal monitor
отдельный material ingestion
отдельные source discovery планы
отдельный policy guard
без единого состояния Learning OS
```

Теперь это собрано в один Learning OS.

## Что реализовано

### 1. Persistent Learning Memory

Файл:

```text
learning/learning_memory.py
```

Хранит в SQLite:

```text
mistakes
lessons
rules
exam results
```

Runtime DB:

```text
data/learning_memory.sqlite3
```

или env:

```text
LEARNING_MEMORY_DB
```

### 2. Unified Learning OS Core

Файл:

```text
learning/learning_os_core.py
```

Собирает в один snapshot:

```text
AI learning packs
financial knowledge
source discovery
legal/policy layers
persistent memory
bot exam loop
training status for 11 bots
```

### 3. Unified Learning OS API

Standalone:

```text
learning/learning_os_app.py
```

Запуск:

```powershell
python -m uvicorn learning.learning_os_app:app --reload
```

Endpoints:

```text
GET  /api/learning-os/snapshot
POST /api/learning-os/close-gap
GET  /api/learning-os/bots/{bot_name}
POST /api/learning-os/mistakes
GET  /learning-os
```

### 4. Dashboard Integration

Файл:

```text
dashboard/learning_os_api.py
```

Main app теперь устанавливает Learning OS endpoints через:

```text
dashboard.app:create_app
```

Главная страница содержит ссылку:

```text
/learning-os
```

### 5. Bot Training Loop

Каждый бот получает:

```text
training pack
financial curriculum
memory lessons
exam score
status ready/needs_training
```

### 6. Close Gap Command

Endpoint:

```text
POST /api/learning-os/close-gap
```

Он создаёт минимальные уроки для всех 11 ботов, если их нет.

## Что считается закрытым

Закрыты эти gaps:

```text
bot_curriculum
financial_knowledge
source_discovery_plan
material_ingestion
legal_monitoring_pipeline
policy_action_guard
persistent_learning_memory
bot_exam_loop
dashboard_learning_os
```

## Что ещё осталось только для продакшена

Это не блокирует закрытие самообучения, но нужно перед реальной эксплуатацией:

```text
1. Подключить live web/search/RSS на сервере.
2. Запустить daily monitor job через cron/GitHub Actions/server scheduler.
3. Добавить human legal review для юридических решений.
4. Подключить реальную торговлю только после sandbox tests и ручного owner approval.
5. Запустить полный CI pytest после каждого изменения.
```

## Проверка

```powershell
python -m pytest learning/tests/test_learning_os.py
python -m pytest dashboard/tests/test_learning_os_dashboard_integration.py
python -m pytest
```

CI уже использует:

```text
python -m pytest
```

значит learning/tests и dashboard/tests должны попадать в общий прогон.

## Главный запуск dashboard

```powershell
python -m uvicorn dashboard.app:app --reload
```

После запуска открыть:

```text
/learning-os
```

## Короткий итог

Learning OS теперь не просто “самообучение на словах”.

Он имеет:

```text
память
уроки
ошибки
правила
экзамены
источники
финансовую базу
юридический мониторинг
policy guard
dashboard
API
тесты
```
