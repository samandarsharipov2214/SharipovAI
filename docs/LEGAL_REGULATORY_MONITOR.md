# Legal & Regulatory Monitor

SharipovAI получил слой юридического и регуляторного мониторинга.

Важно: это не юридическая консультация и не замена юриста.

Это risk/legal intelligence для General Controller.

## Зачем нужно

AI должен понимать, что изменения в законах и правилах могут влиять на:

```text
криптовалюты
акции
биржи
KYC/AML
санкции
налоги
персональные данные
защиту инвесторов
торговые действия
```

## Что реализовано

Файлы:

```text
learning/legal_regulatory_monitor.py
learning/legal_monitor_app.py
learning/tests/test_legal_regulatory_monitor.py
```

Legal Monitor умеет:

```text
строить план мониторинга по региону
знать официальные источники
оценивать юридическое изменение
определять severity
определять affected_bots
давать совет General Controller
создавать summary alerts
```

## Источники

Примеры официальных источников:

```text
sec.gov
cftc.gov
finra.org
federalreserve.gov
irs.gov
treasury.gov
fincen.gov
esma.europa.eu
eba.europa.eu
ecb.europa.eu
fca.org.uk
bis.org
imf.org
fatf-gafi.org
iosco.org
```

## Severity

```text
info
watch
caution
high
critical
```

## Действия для General Controller

```text
continue
watch
caution
manual_review
block_action
```

Если официальный источник сообщает о запрете, санкции, незаконности или критическом ограничении, General Controller должен получить:

```text
block_action
```

Если риск высокий, но не критический:

```text
manual_review
```

## API

Запуск:

```powershell
python -m uvicorn learning.legal_monitor_app:app --reload
```

Endpoints:

```text
GET  /api/legal/policy
GET  /api/legal/plan?region=global
POST /api/legal/evaluate
POST /api/legal/alerts
```

## Пример alert

```json
{
  "title": "Official crypto restriction",
  "topic": "crypto_regulation",
  "source_domain": "sec.gov",
  "source_type": "regulator_docs",
  "summary": "New official rule affects crypto exchange activity."
}
```

## Что ещё не сделано

Пока это planner/evaluator/API.

Следующий этап:

```text
реальный мониторинг сайтов регуляторов
RSS/Atom watcher
поиск новых документов
сравнение старой и новой версии правил
автоматическая отправка alerts в General Controller
страница Legal Monitor в dashboard
```

## Проверка

```powershell
python -m pytest learning/tests/test_legal_regulatory_monitor.py
```

Тесты проверяют:

```text
план мониторинга
официальные источники
not legal advice policy
critical change -> block_action
unofficial news -> watch/caution
summary выбирает самый высокий риск
API endpoints
```
