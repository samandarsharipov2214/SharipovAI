# Material Ingestion Pipeline

SharipovAI получил pipeline для превращения книг, статей, PDF, заметок и учебных материалов в ресурсы для обучения AI-ботов.

## Важное правило

Система не должна превращаться в пиратскую библиотеку.

Она не хранит полный текст чужих книг, платных статей и закрытых материалов.

Вместо этого сохраняется безопасный учебный record:

```text
title
source_type
domain
rights
content_digest
stored_preview
summary
concepts
rules
exam
assigned_bots
```

Поле:

```text
full_text_stored = false
```

## Как работает

```text
материал
↓
нормализация текста
↓
проверка домена и типа источника
↓
короткий конспект
↓
понятия
↓
правила
↓
экзамен
↓
назначение ботам
↓
сохранение safe-record в JSON
```

## Файлы

```text
learning/material_ingestion.py
learning/material_store.py
learning/material_ingestion_app.py
learning/tests/test_material_ingestion.py
```

## Запуск API

```powershell
python -m uvicorn learning.material_ingestion_app:app --reload
```

## API

```text
POST /api/learning/materials
GET  /api/learning/materials
GET  /api/learning/materials/{material_id}
GET  /api/learning/materials/bots/{bot_name}
```

## Пример запроса

```json
{
  "title": "Exchange liquidity lesson",
  "source_type": "course_note",
  "domain": "exchanges",
  "content": "Your own text, notes, or legally provided material..."
}
```

## Что получает бот

Например, Paper Trading Bot может получить:

```text
summary
rules
exam
concepts
```

И использовать это как учебный пакет.

## Где хранится

По умолчанию:

```text
data/learning_materials.json
```

Этот файл является runtime-данными и не должен попадать в GitHub.

Можно задать путь через переменную окружения:

```text
LEARNING_MATERIALS_FILE
```

## Проверка

```powershell
python -m pytest learning/tests/test_material_ingestion.py
```

Тесты проверяют:

```text
материал превращается в safe-record
полный текст не хранится
создаются summary/rules/exam
store сохраняет и обновляет материал
API принимает материал
бот получает только назначенные ему обновления
```

## Следующий шаг

Следующий уровень:

```text
PDF reader
DOCX reader
HTML/article reader
SQLite вместо JSON
страница /learning/materials в dashboard
привязка материалов к Learning Engine
автоматическое создание уроков по ошибкам сделок
```
