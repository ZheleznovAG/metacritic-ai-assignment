# План реализации и поставки

Baseline задачи `PLN-03`, 2026-09-09 (Asia/Novosibirsk). Здесь находятся результаты задач, их декомпозиция, оценки и связи с требованиями/рисками. Статусы, зависимости, приоритет выбора и ворота ведутся **только** в [action_plan.md](action_plan.md); этот файл не является вторым трекером.

Спецификация поведения — [assignment.md](assignment.md), [acceptance.md](docs/requirements/acceptance.md) и [assumptions.md](docs/requirements/assumptions.md). Архитектура — [ADR-0001](docs/decisions/0001-minimal-stack-and-architecture.md), внутренние контракты — [design.md](docs/design.md). Алгоритмы, schema и eval-oracles здесь не дублируются.

## Оценки и резерв

`CTX-01/CTX-02`: дедлайн и доступные часы не заданы; их отсутствие уже принято как ограничение относительного плана. Оценки ниже — инженерные бюджеты до следующего пересмотра, не календарное обещание и не измеренная скорость разработки. Новый денежный расход не принят. Новые сведения о сроке/ёмкости требуют сопоставить остаток задач и резерв до продолжения затронутого scope.

Один исполнитель, один task-cycle за раз. Часы включают author → adversarial review → verify → focused commit; ожидание human input, provisioning, DNS, schedule windows и AI queue не включено. Достижение timebox без evidence требует переоценки/декомпозиции незавершённого остатка; критерий выхода не ослабляется. `PLN-03` имеет текущий timebox 3 часа и не входит в будущую оценку от `G3`.

| Задача | Часы | Проверяемые части / внутренний timebox |
|---|---:|---|
| [IMP-01](#imp-01) | 8 | Runtime/lock и Django bootstrap — 2 ч; Compose/PostgreSQL, secrets/health — 2 ч; CI и clean-start — 2 ч; VDS preflight и ранний endpoint — 2 ч |
| [IMP-02](#imp-02) | 12 | HTML/SSR fixtures и expected extraction — 3 ч; Каталог, identity и migrations — 3 ч; Ingest одной игры и durable jobs — 3 ч; Публичная карточка, upsert и проверки — 3 ч |
| [IMP-03](#imp-03) | 12 | List fixtures, pagination и selector — 4 ч; UTC scheduler, дневной progress и retry — 4 ч; Fake-clock/restart/batch tests и deploy — 4 ч |
| [REV-EVAL-01](#rev-eval-01) | 4 | Full-corpus examples и labels — 2 ч; Metric/threshold/invariants и review — 2 ч |
| [IMP-04](#imp-04) | 20 | Review backend fixtures и page worker — 5 ч; Immutable corpus и selection comparison — 4 ч; Provider/queue/quota/provenance — 5 ч; Card states и failure/capacity/eval — 6 ч |
| [IMP-05](#imp-05) | 8 | List/detail queries и presentation — 4 ч; Combined search/filter/sort и edge tests — 4 ч |
| [SIM-EVAL-01](#sim-eval-01) | 4 | Catalog examples и relevance labels — 2 ч; Metric/threshold/invariants и review — 2 ч |
| [IMP-06](#imp-06) | 6 | Candidate и простой baseline — 3 ч; Frozen comparison и выбор policy — 3 ч |
| [SIM-VER-01](#sim-ver-01) | 3 | DB/card integration — 1 ч; Invariant/navigation/regression checks — 2 ч |
| [IMP-07](#imp-07) | 6 | Chromium E2E с контролируемым входом — 3 ч; Полный Must-path и публичный smoke — 3 ч |
| [HRD-01](#hrd-01) | 6 | Повреждённые HTML/SSR/backend fixtures — 3 ч; HTTP/failure/drift regression — 3 ч |
| [HRD-02](#hrd-02) | 6 | Crash/restart матрица и injection points — 3 ч; State before/after и recovery checks — 3 ч |
| [HRD-03](#hrd-03) | 6 | Barrier tests ingestion и enrichment — 3 ч; Lease expiry/fencing/replay regression — 3 ч |
| [HRD-04](#hrd-04) | 6 | Provider failure/capacity regression — 3 ч; Final contour quality и provenance — 3 ч |
| [HRD-05](#hrd-05) | 8 | Run/job diagnostics и storage measurement — 4 ч; Security/escaping и operational guide — 4 ч |
| [HRD-06](#hrd-06) | 3 | Совместный offline suite и gate audit — 3 ч |
| [PUB-01](#pub-01) | 4 | Production preflight/TLS и versioned deploy — 2 ч; External smoke и resource snapshot — 2 ч |
| [PUB-02](#pub-02) | 4 | Два окна и controlled restart/reboot — 2 ч; Storage/AI capacity и backup/restore evidence — 2 ч |
| [PUB-03](#pub-03) | 2 | Неавторизованный пользовательский smoke — 2 ч |
| [BON-00](#bon-00) | 1 | Scope, оставшееся время и release reserve — 1 ч |
| [BON-21](#bon-21) | 14 | Контракт counters/recovery — 2 ч; Heartbeat и live snapshot — 4 ч; Monitoring UI — 3 ч; Failure/freshness/load checks — 3 ч; Public verification и review — 2 ч |
| [BON-22](#bon-22) | 18 | Auth, sessions и DB grants — 4 ч; Durable admission и общий dispatcher — 5 ч; Operator UI и audit — 3 ч; Auth/concurrency/crash checks — 4 ч; Upgrade/public verification и review — 2 ч |
| [BON-11](#bon-11) | 4 | Search/popularity/transcript probe — 2 ч; Provider units/limitations и disposition — 2 ч |
| [BON-12](#bon-12) | 16 | Замороженный eval/input/output contract — 4 ч; Получение текста и bounded pipeline — 6 ч; Quality/failure/card/E2E verification — 6 ч |
| [REL-02](#rel-02) | 4 | README/evidence index и ограничения — 2 ч; Clean-instructions rehearsal — 2 ч |
| [REL-03](#rel-03) | 4 | Archive inventory/manifest — 2 ч; Privacy/format/completeness review — 2 ч |
| [REL-01](#rel-01) | 6 | Freeze checkout/image и clean verification — 3 ч; Eval/E2E/public/restart/security acceptance — 3 ч |
| [REL-04](#rel-04) | 1 | Финальные URL, manifest и version match — 1 ч |
| [REL-05](#rel-05) | 1 | Reviewable сообщение и подтверждение отправки — 1 ч |

Базовый сценарий без реализации Bonus: **145 часов**, включая `BON-00` для решения о scope; дополнительный резерв **37 часов** (округлённые 25%) даёт **182 часа**. Распределение резерва: 12 ч на интеграционные исправления, 10 ч на source/AI drift, 8 ч на public deployment/recovery, 7 ч на комплект сдачи и повторные проверки. Резерв не расходуется на начало Bonus.

Bonus 2 добавляет оценочно **32 часа + 8 часов отдельного резерва**, Bonus 1 — 20 часов; оба — 52 часа до резерва. Оценка Bonus 2 пересмотрена 2026-09-16 после сверки кода: нужны process heartbeat, live counters/recovery, auth/session storage, изменение DB grants и durable manual admission, отсутствующие в исходной оценке 14 ч. Это инженерные бюджеты, а не подтверждённая скорость. Доступ к публичной среде проверяется перед public verification; при дефиците времени scope пересматривается явным решением, Must не сокращается.

Один исполнитель выполняет базовые 145 часов последовательно. Чистая длина самой длинной цепочки зависимостей — 103 часа при гипотетически независимом выполнении остальных ветвей; это нижняя граница графа, не ускоренный календарный план. Обе величины вычисляет [check_plan.py](research/planning/check_plan.py).

## Порядок и внешнее ожидание

Сначала `IMP-01` проверяет воспроизводимый каркас и ранний публичный endpoint; `IMP-02` даёт первую реальную карточку. Оценка работы самих двух срезов — 20 часов, до завершения остальных функций. Подготовку `REV-EVAL-01` и `SIM-EVAL-01` следует брать сразу после каркаса, чтобы получить конкретные owner decisions до выбора методов; при таком порядке до первой карточки добавляются 8 часов подготовки oracles, а ожидание их принятия допускает независимые `IMP-02/IMP-03`. После ответа возвращаемся к зависимой ветке. Это порядок доступных циклов, а не разрешение выполнять несколько задач одним commit.

Основная зависимая последовательность после `G3`: `IMP-01 → IMP-02 → IMP-03 → IMP-04 → IMP-05 → SIM-VER-01 → IMP-07 → G4`. В `IMP-04` также входит принятый `REV-EVAL-01`; в `SIM-VER-01` — `IMP-06` после `SIM-EVAL-01`. `IMP-04` теперь зависит от `IMP-03`, поскольку использует реальные daily candidates, ownership и восстановление, а не только каталог.

Далее: `G4 → HRD-* → HRD-06 → G5 → PUB-01 → PUB-02 → PUB-03 → G6 → BON-00/GB → REL-02 + REL-03 → REL-01 → REL-04 → REL-05 → G7`. Все hardening-задачи имеют явную зависимость от `G4`; базовые failure/invariant tests входят уже в соответствующие `IMP-*` срезы. Final README и архив готовятся до заморозки, а не после финального acceptance run.

| Условие | Когда проверить / needed-by | Что делать при фактическом отсутствии |
|---|---|---|
| Docker/Compose и deploy-user на VDS | В начале IMP-01, до раннего deploy / G4 | Blocked / Ask: запросить конкретно недостающую capability; независимые eval-oracles доступны |
| Принятие review-selection oracle | После подготовки REV-EVAL-01 / G4, до IMP-04 | Blocked / Ask с одним конкретным вопросом; продолжать только независимые задачи |
| Принятие similarity oracle | После подготовки SIM-EVAL-01 / G4, до IMP-06 | То же правило; metric/threshold не подстраивать после сравнения |
| Hostname, DNS, 80/443, разрешённый reboot | PUB-01/PUB-02 / G6 | Проверить ранее полученные доступы, затем спросить только недостающее |
| Два последовательных реальных hourly windows | PUB-02 / G6 | Отдельное календарное ожидание; заполнение AI queue может потребовать больше двух часов |
| Полный доступный AI export и явная отправка | REL-03/REL-05 / G7 | Сначала подготовить проверяемый manifest/письмо; затем запросить только отсутствующее решение/разрешение |

Сегодня эти условия не объявляются Blocked без факта проверки. Вопросы о дедлайне не блокируют этот относительный baseline. Сам факт наличия credentials в прошлом не заменяет relevant preflight, но уже данное разрешение не запрашивается заново.

## Задачи

Для каждой задачи связи Requirement/Risk заданы в матрицах ниже, входные зависимости и место фактического evidence — в master tracker. Следующее описание задаёт выход и способ его проверки; статус реализации здесь не ведётся.

### IMP-01

Подготовить воспроизводимый каркас и ранний deploy. Тип: Implementation / Delivery.

Выход и проверка: Проект запускается по README из чистого checkout; CI выполняет format/lint/types/tests/build на canonical runtime и PostgreSQL. Versioned image развёрнут на VDS, внешний endpoint доступен; измерены стартовые ресурсы. Layout исходников/тестов документирован в AGENTS.md. Проверка Docker/Compose прав предшествует deploy; отсутствие capability переводит задачу в Ask к G4.

### IMP-02

Провести одну репрезентативную игру end-to-end. Тип: Implementation / Verification.

Выход и проверка: Одна реальная мультиплатформенная игра проходит от источника до публичной карточки со всеми DATA-полями; повтор/alias не создаёт дубль, provenance доступен для диагностики. До parser сохранены sanitised исходные HTML/SSR и независимые expected values; curated observations не выдаются за input fixtures. Проверены non-destructive update, естественный null и атомарность core/job intent. Минимальные записи candidate/job появляются здесь; полный выбор партий — в IMP-03.

### IMP-03

Реализовать batch и календарный цикл. Тип: Implementation / Verification.

Выход и проверка: Плановый процесс сохраняет slots/candidates/progress. Детерминированные проверки покрывают весь AC-SEL, первый/последующий запуск, midnight, overlap списков, exhaustion, retry-first и отсутствие добора после ошибки. Неизменяемый identity/order checkpoint и восстановление после рестарта проверены до включения следующего среза. Внешние run events показывают реальную работу scheduler; окончательные два окна — PUB-02.

### REV-EVAL-01

Заморозить oracle bounded-выборки отзывов. Тип: Evaluation design.

Выход и проверка: Синтетические full-corpus cases покрывают несколько pages/platforms, first/last-page bias, перекос sentiment, редкие темы, дубли, длинный и multilingual текст, deterministic repeat и изменение отзыва вне sample. Метрика, порог и hard invariants принимаются владельцем и фиксируются version/hash до реализации selection comparison. Автор не подстраивает oracle под candidate. После подготовки — обязательный Ask с конкретным вопросом о принятии oracle, needed-by G4 до IMP-04; ожидание отдельно от часов.

### IMP-04

Реализовать раздельный AI-контур отзывов. Тип: Implementation / AI eval.

Выход и проверка: До реализации review parser сохранены backend page/cursor fixtures и expected extraction. Отзывы каждой аудитории собираются по всем известным routes с durable attempts/cursor; retry и partial collections не теряют данные и не публикуют неполный новый corpus. Candidate selection сравнивается с простым baseline на принятом REV-EVAL-01. Groq adapter сохраняет exact input/attempt provenance, валидирует output и token-boundary/provider-unit budget, использует cache, lease, quota reservation и delayed state без paid fallback. Оба резюме видны в карточке; проходят summary eval, source-language, injection, cache/version и [fake-provider cold/unchanged/changed/quota scenarios](research/feasibility/ai-summary.md#capacity-and-residual-limitations). Фиксируются backlog/oldest age и ограничения; async queue не объявляется доказательством достаточной capacity.

### IMP-05

Завершить обязательный пользовательский контур. Тип: Implementation / Verification.

Выход и проверка: Поиск, platform filter и сортировка совместно работают по ASM-15; null/ties, пустой результат, длинные названия и отсутствующие media не ломают UI. Карточка показывает оба резюме и честные pending/stale/insufficient состояния. UI-label language фиксируется как обратимый выбор без перевода source content. UI integration checks и публичный smoke подтверждают AC-UI; screenshot дополняет отчёт.

### SIM-EVAL-01

Заморозить oracle качества похожих игр. Тип: Evaluation design.

Выход и проверка: Независимый golden set включает очевидные matches/non-matches и малую/пустую базу; labels/metric/threshold/hard invariants приняты владельцем и заморожены до comparison. После подготовки oracle задать конкретный Ask, needed-by G4 до IMP-06. Source данных может быть синтетическим; live Metacritic/AI не требуется.

### IMP-06

Реализовать, сравнить и выбрать similarity policy. Тип: Implementation / Evaluation.

Выход и проверка: Оба метода сравниваются на неизменном SIM-EVAL-01; выбран и версионирован простейший прошедший вариант. Comparison report включает все результаты, version/hash oracle и hard invariants. Непройденный threshold означает доработку/пересмотр метода, а не изменение oracle.

### SIM-VER-01

Интегрировать и проверить похожие игры. Тип: Integration verification.

Выход и проверка: Похожие игры отображаются и открывают правильные сохранённые IDs; проверены self-match, duplicates, отсутствие внешних записей вне собственной базы, пустая/малая база, deterministic repeat и relevance regression. Результат подтверждён integration/E2E и публичной карточкой.

### IMP-07

Интегрировать обязательный end-to-end сценарий. Тип: Verification.

Выход и проверка: Один воспроизводимый сценарий проходит от обработки через поиск/filter/sort и полную карточку с двумя резюме до похожей игры. Playwright и browser setup документированы; обычный CI использует fixtures/fakes. Публичный smoke повторяет пользовательский путь на реальных данных. Первичное функциональное evidence покрывает G4.

### HRD-01

Упрочнить внешний контракт и качество данных. Тип: Verification / Hardening.

Выход и проверка: Расширены parser inputs из IMP-02/IMP-04; проверены timeout, bounded retries/rate limiting, 403/429/5xx, исчезновение полей, route/cursor mismatch и partial responses. Каждая ошибка диагностируется и не портит хорошие данные. Отдельный controlled live check не включается в deterministic CI.

### HRD-02

Доказать идемпотентность и восстановление. Тип: Verification / Hardening.

Выход и проверка: Реальные PostgreSQL transactions проверены на сбой до/после core/job commit, на середине page acceptance, retry failed item и restart между запусками. Нет lost intent, дублей, потерянного cursor или перезаписи terminal history. SQL prototype PLN-02 не подменяет эти application tests.

### HRD-03

Доказать безопасность пересекающихся запусков. Тип: Concurrency verification.

Выход и проверка: Два претендента на работу синхронно стартуют на PostgreSQL; только текущий owner подтверждает core/page/summary success. Проверены stale owner, reclaim, late response, повторная доставка и отсутствие двойных counters/claims. Tests не используют SQLite вместо принятого backend.

### HRD-04

Закрыть отказные сценарии AI и регрессию качества. Тип: Verification / AI eval.

Выход и проверка: Timeout, malformed output, quota exhaustion и prompt injection изолированы от batch/UI; сохраняется предыдущий valid summary. Повторены capacity scenarios IMP-04, selected-input/cache/version checks и frozen quality eval конечного контура. Dataset/oracle не изменяются вслед за output; критерии не ослабляются.

### HRD-05

Завершить обязательную наблюдаемость и безопасность. Тип: Implementation / Verification.

Выход и проверка: По run/game/job ID диагностируются успех, ошибка, last success и backlog. Storage report измеряет text versions, повторные observations, attempts, indexes/WAL/backup и headroom на representative corpus; он не подменяется O(unique reviews). Проверены secret boundaries, escaping недоверенных текстов, bounded logs и безопасная реакция на нехватку storage; инструкция не требует Bonus UI.

### HRD-06

Выполнить полный обязательный verification suite. Тип: Verification.

Выход и проверка: На одном проверяемом состоянии проходят static/build, unit/fixture/integration/failure/concurrency, AI/similarity и E2E; каждый критический риск имеет evidence или явно принятое ограничение. Runtime/API live checks отделены. G5 получает ссылки на фактические отчёты.

### PUB-01

Развернуть обязательный release candidate. Тип: Delivery.

Выход и проверка: Проверенный image/commit развёрнут с persistent named volumes, supervision, scoped secrets и UTC scheduler. Проверены DNS/TLS/ingress и ресурсный старт на VDS; URL и безопасные metadata доступны извне. Hostname/порты/права не угадываются: при фактическом отсутствии требуемого доступа — Ask к G6. Это кандидат публичной валидации; окончательная заморозка — REL-01.

### PUB-02

Подтвердить реальную почасовую работу и состояние. Тип: Operational verification.

Выход и проверка: Есть два последовательных фактических application hourly windows и результаты обработки, persistent state переживает restart/redeploy и контролируемый host reboot. Backup восстанавливается в изолированное хранилище без перезаписи рабочей БД. Измерены storage forecast и AI arrivals/cache/completions/backlog/oldest age на реальных данных; sustained недренируемый backlog требует R-AI-02 Replan. Часы в оценке — работа оператора; ожидание расписания, наполнения и доступов отдельно.

### PUB-03

Выполнить внешний пользовательский smoke-test. Тип: External verification.

Выход и проверка: Из внешней сессии на реальных данных проходят список, комбинированный поиск/filter/sort, полная карточка, оба резюме и переход к похожей игре. Сопоставлены версия сервиса, run evidence и ограничения; диагностируемое pending не подменяет наличие подтверждённых рабочих примеров AI. Отчёт закрывает продуктовые/эксплуатационные условия G6.

### BON-00

Принять решение о Bonus scope. Тип: Decision.

Выход и проверка: После G6 выбрать none/bonus1/bonus2/both и записать решение в ADR, отделив выбор ветки от принятия её технических решений. Сверить объём с реальным кодом и оценить оставшуюся поставку/резерв; отсутствие заданного дедлайна не превращать в обещание срока. Невыбранные задачи получают Dropped с основанием; GB закрывается записью решения, если scope пуст. Release reserve не расходуется на старт Bonus. Артефакты решения этого цикла: [ADR-0002](docs/decisions/0002-bonus2-scope.md), [review](docs/requirements/bon_00_review.md); текущий выбор — только в tracker.

### BON-21

Реализовать реальный мониторинг процесса. Тип: Implementation / Verification.

Результат: публичная `/ops/` с состояниями scheduler/worker, текущей работой, историей runs, живыми counters и отдельными очередями reviews/AI. Связи: `OPS-01`, `AC-OPS-01/02`, `ASM-B03`, `R-BON-OPS-01`. Проверяемое предложение — [контракт Bonus 2](docs/bonus2_design.md); решение о транспорте и схеме принимается по evidence этого среза.

Внутренняя декомпозиция (один task-cycle):

1. Зафиксировать definitions found/selected/processed/failed, scope run/day/queue и поведение recovery. Проверить, что сохранённая принадлежность кандидатов партии позволяет получить одинаковые live/terminal counters после повторных attempts; эта работа не сводится к показу `ProcessingRun` в шаблоне.
2. Добавить heartbeat scheduler/worker с instance generation; отдельная DB connection продолжает heartbeat при долгом HTTP. Реализовать согласованный bounded snapshot, публичную allowlist и индексы. Существующие diagnostics переиспользовать там, где совпадает семантика; текущие CLI-ответы не объявлять готовым web API.
3. Собрать templates/CSS/минимальный JS: polling, timestamp, stale/empty/error, reconnect/focus, активный run и история, состояния delayed/failed/unstable, desktop/mobile и доступность с клавиатуры. Подписи English, UTC явно.
4. Проверить на disposable PostgreSQL и Chromium: каждый committed transition <=5 с, counters до финала и после recovery совпадают с независимым oracle, kill/restart и долгий HTTP различимы, refresh/reconnect/out-of-order не создают фиктивного прогресса. Измерить snapshot <=1 с на 10 вкладках и представительном накопленном объёме.
5. Пройти обычный application suite/CI, развернуть versioned candidate, сопоставить публичный DOM с реальными run/job rows и timing log, сохранить screenshots, проверить каталог и выключение monitoring flag. Выполнить adversarial review и focused commit с честным evidence/status.

Затрагиваемые области: `app/processing/` models/migrations/diagnostics/entry points, worker entry point, `app/presentation/`, routes/static assets, `app/tests/`, deployment flags и README. Новые test-файлы добавляются в обычный `scripts/check.py`/CI через существующий discovery; live-проверка остаётся отдельной.

Выход: все `AC-OPS-01/02` доказаны tests, timestamp report и публичным наблюдением; API не раскрывает секреты, наблюдение не меняет ownership. Будущие evidence: `docs/requirements/bon_21_review.md`, screenshots и sanitized timing excerpts в `docs/evidence/`; до их появления ссылки не служат подтверждением.

### BON-22

Реализовать защищённый принудительный запуск. Тип: Implementation / Verification.

Результат: разрешённый оператор запускает одну обычную партию из `/ops/`, видит durable request/run и наблюдает её результат. Связи: `OPS-02`, `AC-OPS-03`, `ASM-B04`, `R-BON-OPS-02`; обязательные concurrency, daily selection, quota и hourly schedule сохраняются. Кандидат access/admission policy записан [до реализации](docs/bonus2_design.md#доступ-оператора-и-права-бд).

Внутренняя декомпозиция (один task-cycle):

1. Добавить Django auth/DB sessions, permission запуска, login/logout и provisioning оператора; отсутствие регистрации/admin UI. Реализовать CSRF, login throttling и session expiry/revocation. Заменить blanket/default grants явной матрицей: web не пишет продуктовые таблицы, background roles не меняют auth/session. Проверить clean install, повтор provisioning и upgrade существующей БД.
2. Добавить durable manual request, idempotency key, глобальные cooldown/rate-limit и audit. Выделить общий admission/execution из scheduled entry point с прежним lease/fencing; HTTP только коммитит команду. Scheduler получает команды без ожидания следующего часа; scheduled timer продолжает работать во время manual batch. Атомарно связать request/run/lease и восстановление после crash.
3. Добавить Run processing и результаты queued/started/busy/rate-limited/expired/failed, безопасный повтор после timeout/refresh, ссылку на run. Авторизация и ограничения проверяются сервером при каждом POST; факт скрытия/disable кнопки не считается защитой.
4. Проверить auth/CSRF/abuse и реальные конкурентные DB connections: один/разные keys, разные вкладки/операторы, два schedulers, scheduled/manual race, переход часа/UTC-дня, crash в каждой границе commit/claim/core completion, fencing и expired request. Проверить неизменность лимита 20, review handoff и Groq quota с fakes; повтор принятого request не делает новых внешних calls.
5. Пройти полный suite/hosted CI, upgrade/rollback rehearsal, затем публичный HTTPS operator journey с реальными данными, наблюдением из второй анонимной сессии и последующим scheduled window. Записать SHA/image identity, sanitized audit/timing и screenshots; обновить README/runbook/evidence, выполнить review и focused commit.

Затрагиваемые области: `app/config/`, `app/processing/` и migrations, `app/presentation/`, management commands, `scripts/provision_db.py` и role/deployment tests, Compose/config examples, application/Chromium tests. Обновить описание layout в AGENTS.md, если появляется отдельный модуль управления.

Выход: `AC-OPS-03` и отсутствие Must-regression подтверждены deterministic suite и публичной демонстрацией; `AC-OPS-01/02` повторно проходят после подключения commands. Будущие evidence: `docs/requirements/bon_22_review.md`, permission/concurrency report, public screenshots/audit и запись `GB` в tracker. Операторский пароль и рабочие credentials передаются приватно; при отсутствии доступа блокируется public verification, а не подменяется mock-демонстрацией.

### BON-11

Проверить реализуемость YouTube-контура. Тип: Discovery spike.

Выход и проверка: Только при Bonus 1: в пределах timebox проверить legitimate video search, gameplay classification, popularity, получение текста и реальные ограничения провайдера. Выход Proceed/Proceed with limitation/Drop bonus с evidence. Если нужен новый аккаунт или расход, Ask к GB; обход источника не используется.

### BON-12

Реализовать и оценить YouTube-заключение. Тип: Implementation / AI eval.

Выход и проверка: Только после положительного BON-11: заранее принять eval/rubric и бюджеты, затем построить трассируемое заключение со ссылкой на выбранное видео. Отсутствие текста, длинный input и ошибки дают честную деградацию. Проверены AC-YT и отсутствие Must-regression. Оценка условная: BON-11 обязан подтвердить её либо перебазировать до начала этой задачи.

### REL-02

Завершить README и evidence index. Тип: Delivery.

Выход и проверка: После решения по Bonus подготовлены README, полный requirement→evidence index, setup/test/deploy commands, расписание/UTC, scope, ограничения и срок доступности. Все шаги предварительно воспроизведены; будущие результаты REL-01/REL-04 обозначены ожидаемыми, а не Verified. Финальный acceptance run выполняется после подготовки этих документов.

### REL-03

Подготовить и проверить AI-архив. Тип: Delivery / Security verification.

Выход и проверка: Подготовлена полная доступная история в исходном порядке с manifest, cutoff и описанием вынужденных изъятий; формат читаем, secrets удалены явно. История сохраняется непрерывно с начала работы, а не реконструируется здесь. Если экспорт недоступен, документировать реальный пробел и Ask к G7, не объявлять комплект полным. Новые проверочные сессии включаются перед отправкой с повторным privacy/manifest check.

### REL-01

Заморозить и полностью проверить release candidate. Тип: Final verification.

Выход и проверка: После подготовки README и архива заморозить проверяемые исходники/config/image и выполнить всю методологию §12.1 на одном кандидате: чистый запуск, полный suite/evals, E2E, публичный smoke, реальное расписание, restart, secrets и ссылки. Release report фиксирует source commit/tree и image digest; публикация evidence не меняет проверенный runtime. Любая правка кода/config/setup после проверки переоткрывает затронутую приёмку, а новый deploy требует соответствующего smoke.

### REL-04

Проверить публичные ссылки извне. Тип: Delivery verification.

Выход и проверка: Из внешней сессии доступны репозиторий, тот же сервис и AI-архив; metadata соответствует REL-01. Archive включает доступные последующие проверочные сессии, manifest/cutoff и privacy scan актуальны. Изменение только архива требует повторной его проверки; изменение runtime возвращает в REL-01. Сохранён финальный dated link-check.

### REL-05

Подготовить и отправить итоговое сообщение. Тип: Delivery.

Выход и проверка: Подготовлено конкретное письмо с проверенными адресом/ссылками/scope/ограничениями и комплектом. Отправка выполняется при явном разрешении владельца; если его ещё нет, Ask к G7 после подготовки письма. Verified требует копии отправленного сообщения и timestamp/подтверждения; наличие draft не закрывает DEL-04.

## Трассировка требований

Каждая строка ссылается на стабильный ID реестра, не меняет Given/When/Then из [acceptance.md](docs/requirements/acceptance.md) и не означает выполнения требования. `YT/OPS` применяются только при выбранном Bonus; `DEL-*` окончательно принимаются к `G7`, а не до `G6`.

| Requirement | Работа | Проверка |
|---|---|---|
| `RUN-01` | `IMP-03` | `PUB-02, REL-01` |
| `SEL-01` | `IMP-03` | `HRD-02, PUB-02` |
| `SEL-02` | `IMP-03` | `HRD-01, HRD-02, PUB-02` |
| `SEL-03` | `IMP-03` | `HRD-02, PUB-02` |
| `DATA-01` | `IMP-02, IMP-03` | `HRD-02, HRD-03, REL-01` |
| `DATA-02` | `IMP-02` | `HRD-01, PUB-03` |
| `DATA-03` | `IMP-02` | `HRD-01, PUB-03` |
| `AI-01` | `REV-EVAL-01, IMP-04` | `HRD-04, PUB-03, REL-01` |
| `AI-02` | `REV-EVAL-01, IMP-04` | `HRD-04, PUB-03, REL-01` |
| `AI-03` | `IMP-04` | `HRD-02, HRD-04, PUB-02` |
| `UI-01` | `IMP-05` | `IMP-07, PUB-03` |
| `UI-02` | `IMP-02, IMP-04, IMP-05` | `IMP-07, PUB-03` |
| `UI-03` | `IMP-05` | `IMP-07, PUB-03` |
| `UI-04` | `IMP-05` | `IMP-07, PUB-03` |
| `UI-05` | `IMP-05` | `IMP-07, PUB-03` |
| `SIM-01` | `SIM-EVAL-01, IMP-06` | `SIM-VER-01, REL-01` |
| `SIM-02` | `SIM-VER-01` | `IMP-07, PUB-03` |
| `SIM-03` | `SIM-VER-01` | `IMP-07, PUB-03` |
| `NFR-01` | `IMP-03` | `HRD-02, PUB-02` |
| `NFR-02` | `IMP-02, IMP-03, IMP-04` | `HRD-02, HRD-04` |
| `NFR-03` | `IMP-03, IMP-04` | `HRD-03` |
| `NFR-04` | `IMP-02, IMP-04` | `HRD-01, HRD-06` |
| `NFR-05` | `IMP-03, IMP-04, HRD-05` | `PUB-02, HRD-06` |
| `NFR-06` | `IMP-01, HRD-05` | `REL-01, REL-03, REL-04` |
| `DEL-01` | `IMP-01, REL-02` | `REL-01, REL-04` |
| `DEL-02` | `IMP-01, PUB-01` | `PUB-02, PUB-03, REL-04` |
| `DEL-03` | `REL-03` | `REL-01, REL-04` |
| `DEL-04` | `REL-05` | `REL-05, G7` |
| `YT-01` | `BON-11, BON-12` | `BON-12, GB` |
| `OPS-01` | `BON-21` | `BON-21, GB` |
| `OPS-02` | `BON-22` | `BON-22, GB` |

## Трассировка рисков

Формулировки, диспозиции и остаточные ограничения принадлежат [risks.md](docs/risks.md). Здесь только связи с будущей работой; 20 Must и 4 Bonus риска не объявляются закрытыми наличием плана.

| Risk | Задачи митигации / проверки |
|---|---|
| `R-EXT-01` | `IMP-02, HRD-01, PUB-01` |
| `R-EXT-02` | `IMP-01, PUB-01, REL-02` |
| `R-EXT-03` | `IMP-02, IMP-04, HRD-01, HRD-05, PUB-02` |
| `R-EXT-04` | `IMP-02, IMP-04, HRD-01` |
| `R-AI-01` | `REV-EVAL-01, IMP-04, HRD-04` |
| `R-AI-02` | `IMP-04, HRD-04, PUB-02` |
| `R-DEP-01` | `IMP-01, PUB-01, PUB-02` |
| `R-DEP-02` | `IMP-01, PUB-03, REL-04` |
| `R-ID-01` | `IMP-02, HRD-02, HRD-03` |
| `R-TIM-01` | `IMP-03, HRD-02, PUB-02` |
| `R-TIM-02` | `IMP-03, HRD-02, HRD-03` |
| `R-DAT-01` | `IMP-02, IMP-04, HRD-01, HRD-02` |
| `R-SIM-01` | `SIM-EVAL-01, IMP-06, SIM-VER-01` |
| `R-OPS-01` | `IMP-03, HRD-05, PUB-02` |
| `R-TST-01` | `IMP-01, IMP-02, IMP-04, HRD-06` |
| `R-SEC-01` | `IMP-01, HRD-05, REL-01, REL-03` |
| `R-DEL-01` | `IMP-01, REL-03, REL-04` |
| `R-PLN-01` | `PLN-03, BON-00` |
| `R-REP-01` | `IMP-01, REL-02, REL-01` |
| `R-UI-01` | `IMP-05, IMP-07, PUB-03` |
| `R-BON-YT-01` | `BON-11, BON-12` |
| `R-BON-YT-02` | `BON-11, BON-12` |
| `R-BON-OPS-01` | `BON-21` |
| `R-BON-OPS-02` | `BON-22` |

## Проверка допущений и границ

| Assumptions | Где сверяются с acceptance |
|---|---|
| ASM-01–ASM-09 | IMP-03, HRD-02, PUB-02: UTC, batch/retry, порядок источников, exhaustion и новый день |
| ASM-10–ASM-13 | IMP-02, HRD-01–HRD-03: identity/platform, alias, null и non-destructive updates |
| ASM-14 | IMP-04/IMP-05, HRD-04: source/summary language и отдельные UI labels |
| ASM-15 | IMP-05/IMP-07: рейтинг при фильтре, ties и null |
| ASM-16–ASM-19 | REV-EVAL-01, IMP-04, HRD-04: completeness/selection, input/contour, insufficient-data и краткость |
| ASM-20–ASM-21 | SIM-EVAL-01, IMP-06, SIM-VER-01: relevance и жёсткие ограничения |
| ASM-22 | IMP-02–IMP-04, HRD-02/HRD-04: partial core/enrichment и точечный retry |
| ASM-23–ASM-26 | IMP-05/IMP-07, PUB-03, REL-02–REL-04: UI/access/browser, архив и его редактирование |
| ASM-B01–ASM-B04 | BON-11/BON-12, BON-21/BON-22: только после выбранного Bonus |

Полное покрытие ID, отсутствие циклов, gate ordering и арифметика бюджета проверяются командой `python -B research/planning/check_plan.py`. Это проверка implementation baseline, не application tests, runtime capacity или принятие ещё не созданных eval-oracles.
