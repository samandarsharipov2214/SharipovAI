# Roles and Access Control

SharipovAI теперь поддерживает базовые роли:

```text
admin
user
```

## Admin

Админ определяется через основной логин владельца.

Админ может открыть:

```text
/security
/api/security/access-requests
/api/security/login-attempts
```

## User

Обычный пользователь может войти в SharipovAI после одобрения заявки, но не может открыть раздел кибер-безопасности.

Если обычный пользователь откроет:

```text
/security
```

он получит:

```text
403 Доступ запрещён
```

Если обычный пользователь откроет security API, он получит:

```json
{"error":"admin_required"}
```

## Правильный защищённый запуск

Для полной защиты использовать:

```powershell
python -m uvicorn dashboard.admin_secure_app:app --reload
```

Этот entrypoint включает:

```text
login
register
request approval
temporary password change
login lockout
admin-only security center
```

## Проверка тестами

Добавлены тесты:

```text
dashboard/tests/test_roles.py
dashboard/tests/test_admin_secure_app_roles.py
```

Они проверяют:

```text
admin получает роль admin
user получает роль user
admin может открыть /security
user не может открыть /security
user не может читать security API
```
