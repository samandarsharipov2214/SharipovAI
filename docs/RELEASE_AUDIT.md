# SharipovAI Release Audit

Перед каждым production deploy и перед любым изменением торгового этапа выполнить:

```bash
python scripts/release_audit.py --runtime --json
```

Команда завершается кодом `1`, если нарушен хотя бы один критический контракт.

## Автоматически проверяется

- ровно девять канонических AI-органов без дублирующихся ID;
- PostgreSQL/SQLite schema доступна;
- execution journal хранится в общей БД и не обрезает evidence;
- `/health`, database status, shared project memory и private-order endpoints зарегистрированы;
- private WebSocket не содержит методов создания, изменения или отмены ордеров;
- Render использует PostgreSQL, migration, `/health` и deploy after checks;
- Web2 собирается перед Python backend;
- Telegram worker использует отдельный runtime script;
- auth включён;
- Testnet и Mainnet execution выключены;
- kill switch включён;
- private order WebSocket выключен по умолчанию;
- legacy exchange credentials запрещены;
- generic `EXCHANGE_API_KEY/SECRET` отсутствуют из blueprint;
- read-only, Testnet и Mainnet credentials разделены;
- Project Guardrails, Full Suite и Windows Agent CI существуют.

## Runtime secrets

Release Audit проверяет только наличие и целостность пар, но никогда не выводит значения.

Обязательные:

- `AUTH_SECRET`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `DATABASE_URL`

Для Telegram production также нужны `BOT_TOKEN` и `TELEGRAM_WEBHOOK_SECRET`; их отсутствие отображается warning, потому что CI не получает production secrets.

Mainnet API key/secret блокируют audit по умолчанию. Они допускаются только отдельным ручным процессом с `RELEASE_AUDIT_ALLOW_MAINNET_CREDENTIALS=1`; этот флаг нельзя добавлять в постоянный Render blueprint.

## Проверка Render после deploy

```text
GET /health
```

Ожидается HTTP 200 и одновременно:

```json
{
  "status": "ok",
  "database": {"status": "ok"},
  "configuration": {
    "status": "ok",
    "kill_switch": true,
    "testnet_execution_enabled": false,
    "live_execution_enabled": false
  }
}
```

Без доступа к Render API значения secrets и реальный deploy не могут быть подтверждены из GitHub. В таком случае audit подтверждает код и blueprint, но production readiness остаётся незавершённой до проверки `/health` на развернутом сервисе.
