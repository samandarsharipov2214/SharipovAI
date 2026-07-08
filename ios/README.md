# SharipovAI iOS

Стартовая версия iOS-приложения SharipovAI на SwiftUI.

## Что внутри

- Темный интерфейс в стиле SharipovAI
- Dashboard
- AI Chat
- Portfolio
- Trades
- Risk
- Settings
- API client для подключения к backend Render

## Как открыть

1. На Mac открой Xcode.
2. Создай новый проект: iOS App, SwiftUI, имя `SharipovAI`.
3. Скопируй папку `ios/SharipovAI` в проект Xcode.
4. В `APIClient.swift` замени `baseURL` на адрес Render.
5. Запусти на iPhone или Simulator.

## Backend

Приложение рассчитано на общий backend:

```text
Website / Telegram Mini App / iOS App -> один SharipovAI API
```
