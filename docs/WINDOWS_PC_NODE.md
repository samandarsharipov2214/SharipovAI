# SharipovAI Windows PC node

ПК используется как локальный рабочий узел и резервное хранилище. Публичный Telegram webhook и внешний Dashboard могут оставаться на Render/VPS; локальный узел по умолчанию слушает только `127.0.0.1` и не открывается в интернет.

## Что устанавливается

- отдельное Python-окружение `.venv`;
- локальная конфигурация `.env.local` с автоматически созданными секретами;
- FastAPI-узел `dashboard:app` на `http://127.0.0.1:8000`;
- проверяемые резервные снимки папки `data` каждые 10 секунд;
- две завершённые копии: `runtime/backups/current` и `runtime/backups/previous`;
- автозапуск web-узла и backup-процесса при входе в Windows;
- проверка web, записи на диск и свежести резервной копии.

## Установка после клонирования репозитория

Откройте PowerShell в папке проекта и выполните:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\setup_pc.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install_autostart.ps1
```

Первичный пароль администратора сохраняется только локально в `runtime/initial_admin_credentials.txt`. После сохранения пароля в безопасном месте удалите этот файл.

## Запуск без перезагрузки

В двух отдельных окнах PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\start_pc_node.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\windows\start_backup.ps1
```

## Проверка

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\check_pc_node.ps1
```

Проверка должна подтвердить запись в `data`, резервную копию моложе 30 секунд и HTTP 200 от `/health`.

## Восстановление после сбоя

1. Остановить SharipovAI.
2. Скопировать содержимое `runtime/backups/current/data` обратно в `data`.
3. Если `current` повреждён, использовать `runtime/backups/previous/data`.
4. Запустить `check_pc_node.ps1`.

## Ограничение текущего этапа

Backup защищает только данные, которые приложение уже записало в `data`. В текущем `main` часть paper-trading состояния ещё сбрасывается потоком runner и не является полностью постоянной. Поэтому подключение PC node не считается полной гарантией восстановления торгового состояния, пока отдельный persistence-слой paper trading не будет внедрён и протестирован.

Реальная торговля остаётся выключенной: `EXCHANGE_LIVE_TRADING_ENABLED=0`, `EXECUTION_KILL_SWITCH=1`.
