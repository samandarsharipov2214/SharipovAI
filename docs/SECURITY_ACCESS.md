# SharipovAI Security Access

## Что уже есть

SharipovAI защищает панель входом через `/login`.

Обычный пользователь не получает доступ сразу. На странице `/register` он отправляет запрос доступа. Запрос попадает в журнал кибер-безопасности.

Админ смотрит запросы здесь:

- `/security`
- `/api/security/access-requests`

## Где хранить пароль

Пароль нельзя хранить в GitHub.

Локально пароль должен быть в `.env`:

```env
ADMIN_USERNAME=Samandar2212
ADMIN_PASSWORD=your-local-password
AUTH_SECRET=long-random-secret
AUTH_ALLOW_REGISTRATION=1
AUTH_USERS_FILE=data/dashboard_users.json
AUTH_ACCESS_REQUESTS_FILE=data/access_requests.json
AUTH_SECURITY_EVENTS_FILE=data/security_events.json
```

На Render эти значения задаются в Environment Variables.

## Что нельзя делать

Нельзя коммитить:

- `.env`
- `data/dashboard_users.json`
- `data/access_requests.json`
- `data/security_events.json`
- базу данных с пользователями

Эти файлы добавлены в `.gitignore`.

## Локальная настройка

Когда будет доступ к ПК:

```powershell
git fetch origin
git reset --hard origin/main
.\scripts\setup_local_env.ps1
python -m pytest
python -m uvicorn dashboard.app:app --reload
```

Потом открыть:

```text
http://127.0.0.1:8000/login
```

## Текущий статус

Это базовая защита для MVP. Для production нужно доработать:

- блокировку после нескольких неудачных попыток входа;
- подтверждение запросов доступа админом;
- роли пользователей;
- хранение пользователей в SQLite/PostgreSQL;
- журнал аудита в базе;
- восстановление пароля;
- двухфакторную защиту.
