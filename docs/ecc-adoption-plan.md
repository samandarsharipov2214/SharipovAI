# SharipovAI — план выборочной адаптации ECC

Дата фиксации: 14 июля 2026 года.

Источник исследования: официальный публичный репозиторий
[`affaan-m/ECC`](https://github.com/affaan-m/ECC), ветка `main`, изученный
коммит `40927950c49f6e742d341e20ff7b9b7e1e7bfff5`. ECC распространяется под
лицензией MIT.

## 1. Решение

SharipovAI не устанавливает ECC целиком и не копирует его дерево агентов,
skills, hooks, команд и локальных баз данных. Используются только подходы,
которые усиливают существующую архитектуру SharipovAI и не создают второго
источника истины.

Каноническими остаются:

- девять AI-органов из `ai_architecture_registry.py`;
- `ProjectDatabase` как единая база состояния, памяти и Evidence;
- существующие `final_project_audit.py` и `release_audit.py`;
- заблокированные testnet/mainnet write-операции;
- General Controller как владелец координации и восстановления;
- Learning Engine как единственный владелец обучения системы.

## 2. Что адаптируется

### 2.1. Fact-forcing перед изменением

Перед изменением критического файла необходимо получить проверяемые факты:

1. кто импортирует или вызывает изменяемый модуль;
2. какие публичные функции, маршруты, схемы и файлы состояния затронуты;
3. существует ли уже компонент с такой обязанностью;
4. как изменение откатывается;
5. какие проверки подтверждают результат.

Это адаптация идеи ECC GateGuard. В SharipovAI она реализуется как проектное
правило и CI-контракт, а не как обязательный внешний hook.

### 2.2. Канонический change ledger

Каждое существенное изменение должно иметь:

- стабильный `change_id`;
- краткое назначение;
- автора/исполнителя;
- список управляемых путей;
- ownership (`managed` или `shared`);
- жизненный цикл `planned -> applied -> verified` либо `failed/rolled_back`;
- Evidence выполненных проверок;
- оптимистическую версию для защиты от конкурентной перезаписи.

Реализация: `storage/change_ledger.py`. Данные сохраняются в существующей
`ProjectDatabase`; отдельная SQLite-база не создаётся.

### 2.3. Doctor

Будущий `doctor` должен быть только читающим и сравнивать:

- каноническую архитектуру;
- ожидаемые маршруты и схемы;
- change ledger и фактическое состояние;
- хеши только управляемых файлов;
- безопасные execution flags;
- состояние общей базы;
- результаты полного pytest, а не только статический процент;
- production/VPS health только при отдельном live-проходе.

Warning и error должны давать ненулевой exit code. Отсутствующие Evidence
нельзя заменять предположением об успешности.

### 2.4. Repair

`repair` появится только после стабилизации doctor и ownership-контракта.
Обязательные свойства:

- dry-run по умолчанию;
- запись плана в change ledger до мутации;
- изменение только `managed` путей;
- запрет абсолютных путей и `..` traversal;
- trusted repository/runtime root;
- резервная копия заменяемого содержимого;
- откат при провале проверки;
- запрет изменения торговых safety flags;
- отсутствие доступа к произвольным shell-командам из данных ledger.

### 2.5. Verification loop

Общий ECC verification loop адаптируется под фактический стек SharipovAI:

1. Python compile/import;
2. полный pytest;
3. архитектурные и API-контракты;
4. безопасность секретов и execution flags;
5. database/migration checks;
6. Web2 asset и JavaScript syntax checks;
7. diff review;
8. отдельный production smoke test после deploy.

Фиксированный процент coverage или наличие конкретного стороннего lint/type
инструмента не считается универсальным критерием готовности. Каждый gate
должен быть установлен в зависимостях и реально выполнен.

### 2.6. Evidence-backed learning

Из ECC Continuous Learning v2 берутся:

- project scope по умолчанию;
- атомарные правила;
- confidence вместе с Evidence;
- снижение confidence при противоречии;
- явное продвижение project rule в global rule.

Не переносятся автоматический сбор всех prompt/tool payload и бесконтрольное
фоновое обучение. В SharipovAI обучение должно:

- сохранять только разрешённые структурированные события;
- удалять секреты и персональные данные;
- быть выключено до настройки источников Evidence;
- не изменять production-код и торговые правила самостоятельно;
- проходить тест и одобрение General Controller;
- никогда не превращать confidence в разрешение реальной сделки.

## 3. Что не переносится

- 261+ ECC skills и 66+ агентов как новые органы SharipovAI;
- отдельный ECC install-state вместо `ProjectDatabase`;
- Claude/Cursor/OpenCode hooks как часть production runtime;
- локальная память, изолированная от общей базы SharipovAI;
- автоматический repair без dry-run, ownership и trusted root;
- массовое копирование конфигураций в пользовательский home-каталог;
- auto-promotion в live trading, production deploy или destructive operation;
- декоративные проценты готовности без полного набора тестов;
- запись токенов, паролей, API keys или raw credentials в ledger/Evidence.

## 4. Обнаруженные нюансы ECC

ECC сам документирует, что часть target-specific merge/remove semantics и
lifecycle-команд остаётся на раннем/scaffold уровне. Поэтому его installer,
doctor и repair нельзя считать готовым универсальным модулем для прямого
переноса.

ECC также рассматривает install-state как потенциально атакуемый ввод и
ограничивает repair/uninstall trusted root. Для SharipovAI это обязательное
условие, а не дополнительная защита.

Project-scoped learning уменьшает смешивание правил между репозиториями, но не
решает вопросы privacy, secret filtering и ложного обучения. Эти проверки
должны выполняться до включения фонового наблюдения.

## 5. Этапы внедрения

### Этап 1 — Foundation

- [x] создать отдельную GitHub-ветку;
- [x] добавить `ProjectChangeLedger` поверх общей базы;
- [x] запретить unsafe paths и sensitive metadata keys;
- [x] исправить подтверждённые ошибки Virtual Account rendering;
- [x] исправить сохранение ошибок AI-organ monitor;
- [ ] получить зелёный CI для нового набора изменений.

### Этап 2 — Truthful verification

- включить результат полного pytest в итоговый аудит;
- разделить static, integration и live evidence;
- исключить отчёт `100%`, если полный pytest красный;
- сохранять verification result в change ledger.

### Этап 3 — Read-only doctor

- добавить детерминированный doctor без мутаций;
- проверять каноническую БД и параллельные state stores;
- проверять 9 AI-органов против legacy 11-bot интерфейсов;
- выдавать машинный JSON и понятный отчёт.

### Этап 4 — Safe repair

- сначала dry-run plan;
- затем управляемые операции с backup и rollback;
- включить только после зелёных тестов doctor/ledger/path-safety.

### Этап 5 — Controlled learning

- перенести Bot Communication на общую ProjectDatabase;
- добавить project/global scopes и Evidence confidence;
- включать автоматический observer только после redaction и privacy tests.

## 6. Правило готовности

Изменение считается выполненным только когда одновременно существуют:

1. commit/PR;
2. запись change ledger;
3. выполненные проверки с фактическим результатом;
4. отсутствие ослабления safety flags;
5. понятный rollback;
6. для production — отдельный smoke test после deploy.

До завтрашних локальных/VPS-проверок изменения этой ветки остаются draft и не
должны автоматически объединяться в `main`.
