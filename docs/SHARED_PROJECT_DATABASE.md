# Единая база SharipovAI

## Назначение

`storage.ProjectDatabase` является каноническим хранилищем для общей памяти проекта, состояний девяти AI-органов, evidence-событий и критических snapshot-данных. JSON-файлы после миграции используются только как локальный cache/backup.

## Production

Render создаёт PostgreSQL `sharipovai-db` и передаёт `DATABASE_URL` сервису автоматически. Перед каждым deploy выполняется:

```bash
python scripts/migrate_project_db.py
```

`SHARIPOVAI_DATABASE_REQUIRED=1` запрещает production-запуск без базы.

## Локальная разработка

Без `DATABASE_URL` используется единый файл:

```text
data/sharipovai_shared.db
```

Локальный fallback запрещается установкой `SHARIPOVAI_DATABASE_REQUIRED=1`.

## Общая память чатов

Authenticated API:

```text
POST /api/project-memory/messages
GET  /api/project-memory/messages?project_id=SharipovAI
```

Сообщения разных `chat_id` сохраняются в одном `project_id`, поэтому все интерфейсы SharipovAI могут читать общую историю проекта.

## Обязательные Render secrets

Добавить в Render Environment, не в GitHub:

- `AUTH_SECRET`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `BOT_TOKEN`
- `WEBAPP_URL`
- `TELEGRAM_WEBHOOK_SECRET`
- `BYBIT_READONLY_API_KEY`
- `BYBIT_READONLY_API_SECRET`
- `BYBIT_TESTNET_API_KEY`
- `BYBIT_TESTNET_API_SECRET`

`BYBIT_MAINNET_API_KEY` и `BYBIT_MAINNET_API_SECRET` не добавляются до отдельного ручного разрешения Mainnet. Для всех Bybit-ключей вывод средств должен быть отключён.

Старые `EXCHANGE_API_KEY` и `EXCHANGE_API_SECRET` не используются, пока явно не установлен временный migration-флаг `BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS=1`. В production этот флаг обязан оставаться `0`.

## Проверка

```bash
python scripts/migrate_project_db.py
python -m pytest -q tests/test_project_database.py tests/test_database_api.py tests/test_bybit_credentials.py
```

Readiness:

```text
GET /health
```

Endpoint не выводит DSN, API keys или secrets.
