# Evidence Vault, Decision Replay & Impact Tracker

SharipovAI получил слой памяти решений и доказательств.

## Зачем это нужно

ИИ должен уметь ответить:

```text
почему было принято решение?
какие источники были использованы?
какой был confidence?
какой был риск?
что произошло потом?
какой источник подтвердился или ошибся?
какой урок создать для Learning OS?
```

## Что реализовано

### 1. Evidence Vault

Файл:

```text
learning/evidence_vault.py
```

SQLite DB:

```text
data/evidence_vault.sqlite3
```

или env:

```text
EVIDENCE_VAULT_DB
```

Хранит:

```text
decisions
evidence
outcomes
source_reputation
```

### 2. Decision Replay

Endpoint:

```text
GET /api/evidence-vault/decisions/{decision_id}/replay
```

Возвращает:

```text
исходное решение
источники
confidence
risk_level
reason
outcomes
replay text
```

### 3. Impact Tracker

Endpoint:

```text
POST /api/evidence-vault/decisions/{decision_id}/outcome
```

Позволяет записать результат решения:

```json
{
  "outcome": "confirmed",
  "impact_score": 1.0,
  "learning_signal": "positive"
}
```

или негативный результат:

```json
{
  "outcome": "contradicted",
  "impact_score": -1.0,
  "learning_signal": "negative",
  "notes": "Source was later contradicted by official data."
}
```

### 4. Source Reputation

Источники получают trust score.

Если источник подтверждается:

```text
trust_score растёт
confirmed +1
```

Если источник опровергнут:

```text
trust_score падает
contradicted +1
```

### 5. Learning OS bridge

Файл:

```text
learning/evidence_learning_bridge.py
```

Если outcome негативный, система создаёт mistake + lesson в Learning OS.

### 6. API + Dashboard

Standalone:

```text
learning/evidence_vault_app.py
```

Dashboard integration:

```text
dashboard/evidence_vault_api.py
```

Main dashboard page:

```text
/evidence-vault
```

Endpoints:

```text
GET  /api/evidence-vault/snapshot
POST /api/evidence-vault/decisions
GET  /api/evidence-vault/decisions
GET  /api/evidence-vault/decisions/{decision_id}/replay
POST /api/evidence-vault/decisions/{decision_id}/outcome
GET  /api/evidence-vault/sources
```

### 7. Automatic recorder

Файл:

```text
dashboard/evidence_recorder_middleware.py
```

Best-effort записывает успешные ответы risky endpoints:

```text
/api/run
/api/trade-gate
```

Если запись не получится, endpoint не падает.

## Главный запуск

```powershell
python -m uvicorn dashboard.app:app --reload
```

Открыть:

```text
/evidence-vault
```

## Проверка

```powershell
python -m pytest learning/tests/test_evidence_vault.py
python -m pytest dashboard/tests/test_evidence_vault_dashboard_integration.py
python -m pytest dashboard/tests/test_evidence_recorder_middleware.py
python -m pytest
```

## Что это добавляет к самообучению

Теперь Learning OS получает не только ручные ошибки, но и реальные последствия решений:

```text
решение
↓
источники
↓
outcome
↓
source reputation
↓
lesson if negative
↓
training memory
```

Это делает SharipovAI более проверяемым, честным и обучаемым.
