# AI Source Discovery

Learning Engine должен сам искать учебные источники для AI-ботов.

Пользователь не должен вручную искать каждую статью, книгу или документ.

## Что делает Source Discovery

Файлы:

```text
learning/source_discovery.py
learning/source_discovery_app.py
learning/tests/test_source_discovery.py
```

Система строит план поиска:

```text
какому боту что нужно изучить
какие домены нужны
какие запросы выполнить
какие источники предпочитать
какие источники запрещены
как валидировать найденное
как ранжировать источники
```

## Разрешённые источники

```text
official
open_access
exchange_docs
regulator_docs
public_course
book_metadata
whitepaper
```

## Запрещённые источники

```text
pirated_book
paid_article_fulltext
leaked_report
unknown_copyright_fulltext
```

## Важное правило по книгам

Если книга не является открытой или пользователь не загрузил её сам, система не должна сохранять полный текст.

Можно сохранять:

```text
название
автор
тема
чему учит
каким ботам нужна
краткие заметки
правила
экзамен
```

Нельзя сохранять:

```text
полный текст платной книги
пиратский PDF
закрытую статью целиком
утекший отчёт
```

## API

Запуск:

```powershell
python -m uvicorn learning.source_discovery_app:app --reload
```

Endpoints:

```text
GET  /api/learning/discovery/policy
GET  /api/learning/discovery/plan
GET  /api/learning/discovery/plan/{bot_name}
POST /api/learning/discovery/validate
POST /api/learning/discovery/rank
```

## Пример работы

Risk Engine получает задачи:

```text
искать источники по risk
искать источники по trading
искать источники по exchanges
искать источники по financial_institutions
```

News Agent получает задачи:

```text
crypto
stocks
macro
regulation
```

## Что ещё не сделано

Этот блок пока создаёт planner и API.

Следующий этап:

```text
реальный search connector
загрузка результатов поиска
извлечение metadata
создание safe summary
передача в Material Ingestion Pipeline
запись в learning_materials.json или SQLite
```

## Проверка

```powershell
python -m pytest learning/tests/test_source_discovery.py
```

Тесты проверяют:

```text
план поиска для бота
политику источников
запрет пиратских материалов
принятие официального источника
ранжирование доверенных источников
API endpoints
```
