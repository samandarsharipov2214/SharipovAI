# SharipovAI correctness gates

Проект считается готовым к следующему этапу только при одновременном выполнении всех условий.

## Runtime

- `/health` возвращает HTTP 200;
- PostgreSQL schema migration выполнена;
- Dashboard импортируется без startup warning;
- Web2 health-check проходит;
- Telegram работает только в webhook-режиме на Render;
- Windows PC Agent использует один supervisor-процесс.

## Безопасность

- auth включён (`SHARIPOVAI_DISABLE_AUTH=0`);
- `EXECUTION_KILL_SWITCH=1`;
- `TESTNET_EXECUTION_ENABLED=0` до отдельного Testnet-этапа;
- `EXCHANGE_LIVE_TRADING_ENABLED=0`;
- Mainnet credentials отсутствуют;
- legacy exchange credentials выключены;
- withdrawal permission отсутствует у всех Bybit keys.

## Данные

- общая память чатов записывается через `ProjectDatabase`;
- состояния AI-органов используют канонические `organ_id`;
- Bybit account snapshot сохраняется в PostgreSQL и JSON backup;
- corrupt storage или missing evidence возвращают BLOCK/503;
- backup и restore проверены после принудительного завершения процесса.

## CI

- database migration — success;
- compileall — success;
- dashboard import — success;
- execution lock assertion — success;
- full pytest — success;
- Web2 build — success;
- Windows Agent tests — success.

Ни один пункт нельзя заменять предположением или отсутствием красного статуса.
