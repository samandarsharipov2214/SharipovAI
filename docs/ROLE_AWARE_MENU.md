# Role-aware menu

В защищённой версии SharipovAI меню теперь зависит от роли пользователя.

## Admin

Админ видит ссылку:

```text
Кибер-безопасность
```

И может открыть:

```text
/security
```

## User

Обычный пользователь не должен видеть ссылку на раздел кибер-безопасности в меню.

Даже если пользователь вручную откроет адрес:

```text
/security
```

он всё равно получит отказ:

```text
403 Доступ запрещён
```

## Где реализовано

```text
dashboard/menu_visibility.py
```

Этот модуль удаляет admin-only ссылку из HTML для обычного пользователя.

Подключение находится в production-entrypoint:

```text
dashboard/admin_secure_app.py
```

## Проверка

Добавлен тест:

```text
dashboard/tests/test_menu_visibility.py
```

Он проверяет:

```text
admin сохраняет ссылку на /security
user не видит ссылку на /security
ссылка Выйти остаётся на месте
```

Для полной проверки запускать:

```powershell
python -m pytest
```
