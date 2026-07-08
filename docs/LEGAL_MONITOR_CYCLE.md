# Legal Monitor Cycle

SharipovAI получил крупный цикл юридического мониторинга:

```text
official feed / fetched items
↓
feed parser
↓
legal watcher
↓
last_seen state
↓
legal alerts
↓
General Controller advice
↓
Learning Engine material
```

## Файлы

```text
learning/legal_feed_fetcher.py
learning/legal_monitor_cycle_app.py
learning/tests/test_legal_feed_fetcher.py
```

## Что умеет

```text
1. Иметь реестр RSS/Atom feeds официальных источников.
2. Парсить RSS/Atom записи.
3. Превращать feed entry в legal item.
4. Передавать items в Legal Source Watcher.
5. Дедуплицировать уже увиденные документы.
6. Создавать legal alerts.
7. Формировать controller_advice для General Controller.
8. Превращать legal alert в safe learning material.
```

## Реестр feeds

Первые feeds:

```text
SEC press releases RSS
FINRA news releases RSS
FCA news RSS
```

Они находятся в:

```text
DEFAULT_FEEDS
```

## API

Запуск:

```powershell
python -m uvicorn learning.legal_monitor_cycle_app:app --reload
```

Endpoints:

```text
GET  /api/legal/cycle/feeds?region=us
POST /api/legal/cycle/run
```

## Offline / test mode

Можно передать items вручную:

```json
{
  "use_live_feeds": false,
  "items": [
    {
      "title": "Official crypto exchange ban",
      "topic": "crypto_regulation",
      "source_domain": "sec.gov",
      "source_type": "regulator_docs",
      "url": "https://sec.gov/news/crypto-ban",
      "summary": "Official new rule says crypto exchange activity is illegal and banned."
    }
  ]
}
```

## Live feed mode

Можно включить live feeds:

```json
{
  "use_live_feeds": true,
  "region": "us",
  "items": []
}
```

Тогда система попробует получить RSS/Atom feeds из реестра.

## General Controller advice

Если найден критический официальный документ, controller получает:

```text
recommended_action = block_action
must_notify_owner = true
```

Если документ повторный, он не создаёт новый alert:

```text
new_count = 0
duplicate_count = 1
recommended_action = continue
```

## Learning Engine material

Каждый legal alert превращается в safe learning material:

```text
title
source_type = official_document
domain = regulation
summary/rules/exam
full_text_stored = false
```

Так юридическое изменение становится уроком для ботов.

## Проверка

```powershell
python -m pytest learning/tests/test_legal_feed_fetcher.py
```

Тесты проверяют:

```text
RSS parsing
feed registry
legal monitor cycle
controller advice
learning material generation
deduplication
API cycle
```

## Что осталось сделать дальше

```text
1. Добавить больше официальных feeds.
2. Добавить HTML sitemap/search fetcher для сайтов без RSS.
3. Добавить расписание ежедневного мониторинга.
4. Добавить dashboard-страницу Legal Monitor.
5. Сохранять alerts в отдельный журнал.
6. Связать block_action с реальным запретом торговых действий.
```
