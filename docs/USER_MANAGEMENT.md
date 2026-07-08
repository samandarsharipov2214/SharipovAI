# User Management

SharipovAI получил отдельный слой управления пользователями.

## Правильный запуск

Для версии с управлением пользователями запускать:

```powershell
python -m uvicorn dashboard.user_admin_app:app --reload
```

Этот entrypoint включает всё, что было раньше:

```text
вход
заявки доступа
одобрение заявок
временный пароль
смена временного пароля
защита от перебора
роли admin/user
admin-only security center
role-aware menu
```

И добавляет управление пользователями.

## Страница

```text
/security/users
```

Админ видит список пользователей:

```text
логин
роль
активен
нужна ли смена пароля
дата создания
```

## API

```text
GET  /api/security/users
POST /api/security/users/{username}/disable
POST /api/security/users/{username}/enable
POST /api/security/users/{username}/promote
POST /api/security/users/{username}/demote
POST /api/security/users/{username}/reset-password
```

## Возможности

Админ может:

```text
отключить пользователя
включить пользователя
повысить пользователя до admin
понизить admin до user
сбросить пароль
выдать новый временный пароль
```

## Безопасность

API находится под `/api/security`, поэтому обычный пользователь не должен иметь доступ к этим операциям.

При сбросе пароля:

```text
создаётся новый временный пароль
старый пароль перестаёт работать
must_change_password становится true
пользователь должен сменить пароль при входе
```

## Проверка

Добавлены тесты:

```text
dashboard/tests/test_user_admin.py
```

Они проверяют:

```text
создание пользователя
список пользователей без password_hash
отключение пользователя
включение пользователя
смену роли
сброс пароля
проверку временного пароля
ошибки для неизвестного пользователя
ошибку для неправильной роли
```
