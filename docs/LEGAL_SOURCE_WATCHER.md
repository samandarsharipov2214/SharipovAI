# Legal Source Watcher

SharipovAI получил рабочий каркас мониторинга юридических и регуляторных источников.

## Что теперь есть

Файлы:

```text
learning/legal_source_watcher.py
learning/legal_watcher_app.py
learning/tests/test_legal_source_watcher.py
```

Watcher делает:

```text
1. Принимает найденные legal/regulatory items.
2. Сравнивает их с last_seen state.
3. Новые документы превращает в legal alerts.
4. Повторы не дублирует.
5. Создаёт controller_advice для General Controller.
6. Сохраняет state в JSON.
```

## Где он мониторит

Реестр официальных источников находится в:

```text
DEFAULT_LEGAL_SOURCES
```

Примеры источников:

```text
sec.gov
cftc.gov
fincen.gov
irs.gov
esma.europa.eu
eur-lex.europa.eu
fca.org.uk
fatf-gafi.org
bis.org
```

## Важно

Текущий watcher ещё не скачивает сайты сам напрямую.

Он уже умеет принимать результаты от будущего fetch/search/RSS connector и обрабатывать их правильно.

Следующий слой должен делать:

```text
RSS/Atom fetch
official website search
document metadata extraction
HTML/PDF detection
passing fetched items into watcher
```

## State

По умолчанию state хранится тут:

```text
data/legal_watch_state.json
```

Можно изменить через env:

```text
LEGAL_WATCH_STATE_FILE
```

State хранит fingerprints уже увиденных документов, чтобы не создавать одинаковые alerts снова.

## API

Запуск:

```powershell
python -m uvicorn learning.legal_watcher_app:app --reload
```

Endpoints:

```text
GET  /api/legal/watch/sources?region=us
POST /api/legal/watch/run
```

## Пример входа

```json
{
  "items": [
    {
      "title": "Official crypto exchange restriction",
      "topic": "crypto_regulation",
      "source_domain": "sec.gov",
      "source_type": "regulator_docs",
      "url": "https://sec.gov/example/crypto-restriction",
      "summary": "Official new rule says this crypto exchange activity is illegal and must be banned."
    }
  ]
}
```

## Что получает General Controller

```text
recommended_action
must_notify_owner
affected_bots
instructions
summary
```

Если риск критический:

```text
recommended_action = block_action
must_notify_owner = true
```

Инструкции могут быть:

```text
Block related trading or access actions until manual legal review.
Notify owner immediately.
Lower confidence for all affected bots.
Create a learning material from the legal alert.
```

## Проверка

```powershell
python -m pytest learning/tests/test_legal_source_watcher.py
```

Тесты проверяют:

```text
реестр источников по региону
создание alert из нового документа
controller advice для General Controller
дедупликацию повторов
сохранение last_seen state
API watcher
```
