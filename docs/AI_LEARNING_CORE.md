# AI Learning Core

SharipovAI получил первый реальный слой обучения внутренних AI-ботов.

Важно: это не магическое самообучение и не автоматическое изменение production-кода.

Это контролируемое обучение:

```text
уроки
правила
ошибки
обязательные проверки
экзамены
учебные пакеты для каждого бота
```

## Почему так

Опасно давать AI право самому менять себя без проверки. Поэтому Learning Engine должен не переписывать систему тайно, а создавать проверяемые учебные ресурсы.

Правильный цикл:

```text
ошибка или результат
↓
урок
↓
правило
↓
обязательная проверка
↓
экзамен
↓
только потом внедрение в поведение бота
```

## Боты

Учебные пакеты есть для 11 AI-ботов:

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

## API

Learning Core имеет отдельный entrypoint:

```powershell
python -m uvicorn learning.learning_app:app --reload
```

API:

```text
GET  /api/learning/manifest
GET  /api/learning/bots/{bot_name}
POST /api/learning/bots/{bot_name}/exam
```

## Что получает бот

Каждый бот получает:

```text
goal
lessons
required_checks
common_mistakes
exam
```

Пример: News Agent получает дополнительные проверки:

```text
second_source_checked
source_trust_checked
retraction_checked
```

Risk Engine получает:

```text
drawdown_checked
max_loss_checked
capital_preservation_checked
```

Learning Engine получает:

```text
lesson_created
rule_created
exam_created
```

## Тесты

Добавлены тесты:

```text
learning/tests/test_ai_learning_core.py
```

Они проверяют:

```text
все 11 ботов имеют учебные пакеты
глобальные правила существуют
Learning Engine имеет специальные уроки
экзамен считает результат
API отдаёт учебный пакет
API принимает экзамен
```

## Дальше нужно усилить

Следующий уровень:

```text
SQLite-память уроков
сохранение ошибок сделок
автоматическое создание урока из ошибки
версионирование правил
связь Learning Engine с AI Bots API
страница /learning в dashboard
```
