# Login Lockout Protection

SharipovAI теперь имеет отдельный защищённый entrypoint:

```powershell
python -m uvicorn dashboard.secure_app:app --reload
```

Он добавляет защиту от перебора пароля поверх основной панели.

## Как работает

1. Пользователь вводит неверный пароль.
2. Система считает неудачную попытку.
3. После лимита попыток пользователь временно блокируется.
4. Даже правильный пароль не пустит до окончания блокировки.
5. События пишутся в журнал кибер-безопасности.

## Настройки окружения

Названия переменных:

```text
AUTH_LOGIN_ATTEMPTS_FILE
AUTH_MAX_FAILED_ATTEMPTS
AUTH_LOCK_SECONDS
```

Рекомендуемые значения:

```text
AUTH_LOGIN_ATTEMPTS_FILE -> data/login_attempts.json
AUTH_MAX_FAILED_ATTEMPTS -> 5
AUTH_LOCK_SECONDS -> 900
```

## API проверки

```text
GET /api/security/login-attempts
```

Ответ показывает:

```text
failed_attempts
locked
locked_until
seconds_left
last_failed_at
last_success_at
```

## Проверка тестами

Добавлен тест:

```text
dashboard/tests/test_secure_app_lockout_flow.py
```

Он проверяет полный поток:

```text
неверные пароли -> блокировка -> правильный пароль временно не пускает -> API показывает блокировку
```
