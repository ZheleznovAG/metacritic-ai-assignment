# Детальное ревью текущего состояния проекта

Дата: 2026-09-13. Проверенный commit: `6551e42badb1bb98ae53c9772fd386620097301d`.
Рабочее дерево отслеживаемых файлов было чистым до проверки и после неё.

**Вердикт: Changes requested. Проект пока не готов к приёмке обязательной части.**
Контейнерная сборка, штатные проверки и локальный HTTP-путь работают. Из 15 замечаний
предыдущего аудита исправлены R02 и R15, остальные 13 воспроизведены на текущем SHA.
Дополнительно воспроизведены шесть замечаний R16–R21. Всего открыто 19 замечаний:
7 P1 и 12 P2. P1 означает существенное нарушение корректности обязательного контура;
P2 — исправимый дефект границ, надёжности или отображения. P0 не обнаружено.

Это отдельное ревью, а не цикл исправления реализации. Текущие task/gate-статусы
по-прежнему принадлежат [action_plan.md](../../action_plan.md). Номера R01–R15
сохранены из [индекса предыдущего аудита](implementation_audit_2026_09_13.md).
R16–R21 — новые номера этого отчёта; связанные IMP-задачи указаны в master tracker.

## Объём и доказательства

Проверены требования и acceptance, принятые контракты `docs/design.md`, актуальный
tracker, код discovery/scheduler/core ingest, collector/corpus/selection,
AI adapter/worker/quota, запросы и шаблоны UI, Django settings, Compose/Dockerfile/CI.
Контрпримеры исполнены с реальной PostgreSQL; HTTP Metacritic/Groq заменён fixtures
и `httpx.MockTransport`. Конкурентный quota probe использует два соединения PostgreSQL.

| Проверка | Фактический результат | Сохранённое evidence |
|---|---|---|
| `.\.venv-app\Scripts\python.exe -B scripts/check.py` | Exit 0; 177 application tests, 6 scripts tests, 18 planning tests, 7 AI evidence tests, 9 selection tests; format/lint/mypy/migrations/static/planning/oracles прошли | [output excerpts](../../research/reviews/6551e42/verification.txt) |
| `docker compose --env-file .env.app build web checks` | Оба образа текущего worktree собраны | [original log SHA-256](../../research/reviews/6551e42/source_hashes.json) |
| `docker compose --env-file .env.app run --rm checks` | Exit 0; Linux/Python 3.12, 177 application tests и остальные штатные проверки прошли | [output excerpts](../../research/reviews/6551e42/verification.txt) |
| `.\.venv-app\Scripts\python.exe -B research/reviews/6551e42/reproduce.py` | 24 probes, OK: 2 проверяют исправления, 22 подтверждают дефектное поведение, сгруппированное в 19 findings | [reproduce.py](../../research/reviews/6551e42/reproduce.py), [observations](../../research/reviews/6551e42/observations.json) |
| `docker compose --env-file .env.app --profile app up -d --wait` | Provisioning/migrations/web/Caddy успешно запускаются с существующей локальной БД | [original log SHA-256](../../research/reviews/6551e42/source_hashes.json) |
| `scripts/smoke.py http://127.0.0.1:18081 --version local` | Главная/health/CSS работают; env/admin/unknown дают ожидаемые 404 | [output excerpts](../../research/reviews/6551e42/verification.txt) |
| HTTP-проверка карточки и поиска | `/games/1/` отвечает 200 и содержит core/platform/summary sections; заведомо отсутствующее название не возвращает карточек; список содержит 41 ссылку на игры | [output excerpts](../../research/reviews/6551e42/verification.txt) |
| `git diff --check` | Exit 0 | Команда воспроизводима из корня |

**OK у defect probes означает, что ожидаемый дефект воспроизведён, а не что приложение
правильно.** Они предназначены для анализа; при исправлениях нужны application
регрессии с ожидаемым правильным исходом. После проверки временные web/Caddy
остановлены, исходная работающая PostgreSQL и данные сохранены. Полные исходные логи остались в ignored `.artifacts/review-current/`; их SHA-256,
санитизированные excerpts, все 24 observations и воспроизводимый probe опубликованы
в [архиве](../../research/reviews/6551e42/README.md). Это evidence локальной сессии,
не hosted CI. Hash без полного лога не заменяет независимое воспроизведение build/startup.

В этой сессии не проверялись hosted CI, текущий VDS, доступность живого Metacritic,
живой Groq, браузерный E2E, reboot/restore или нагрузочная ёмкость. Локальный запуск
использовал существующую БД; он не заявляется проверкой абсолютно чистого deployment.
Секреты и operator configuration не печатались; полный аудит секретов всей истории
Git и AI-архива не выполнялся.

## Новые замечания

### R16 — P1: устаревший core process изменяет уже обработанного кандидата

Код: [runner.py:41](../../app/processing/runner.py#L41),
[selector.py:34](../../app/processing/selector.py#L34).
Связь: IMP-03 / HRD-03, `NFR-03`, `AC-NFR-03`, `R-TIM-02`, fencing contract design.

`process_candidate()` записывает `state=processing` до транзакции с
`verify_fencing_token()`. Если старый процесс остановился перед этой записью,
новый владелец lease успел обработать кандидата, а старый затем продолжился,
он возвращает уже обработанного кандидата в `processing`. Поздняя проверка
выбрасывает `StaleRun`, но ранняя запись остаётся. Обычный следующий tick переводит
такую строку в `retryable` и успешно обрабатывает игру второй раз в тот же день.

Probe `test_19`: `processed → processing` от старого owner, затем
`reprocessed_same_day=1`. Это воспроизводится без повреждения БД или обхода API;
тест задаёт допустимый порядок остановки/возобновления двух владельцев lease.
Нужно проверять owner/token и допустимое состояние под блокировкой **до любой
записи кандидата**, включая recovery, и проверять fencing на всех переходах.

### R17 — P2: корректный cache hit навсегда отображается как незавершённое обновление

Код: [worker.py:40](../../app/summaries/worker.py#L40),
[presentation/summaries.py:86](../../app/presentation/summaries.py#L86).
Связь: IMP-04/05, `AI-03`, `AC-AI-05`, `UI-02`.

По контракту изменение вне выбранного sample создаёт новый corpus с прежним
`model_input_fingerprint`. `ensure_job()` правильно возвращает существующий
успешный job, но его FK `source_corpus` остаётся прежним. UI ищет job только по FK
самого нового corpus, не находит его и навсегда показывает
`stale / collection_in_progress`. Никакой работы, способной убрать этот статус,
в очереди нет. Отображаемые coverage counters также остаются от старого corpus.

Probe `test_20`: одинаковый model input, разные corpora, job=`succeeded`,
UI=`stale`, `claim_next_job()` возвращает `None`. Исправление должно разрешать
текущий результат по input/contour identity и сохранять происхождение старого
summary, одновременно показывая актуальное состояние collection/corpus.

### R18 — P2: минимальный порог применяется до дедупликации входа

Код: [worker.py:95](../../app/summaries/worker.py#L95),
[corpus.py:179](../../app/reviews/corpus.py#L179).
Связь: IMP-04, `AC-AI-04`, `R-AI-02`, deterministic sparse-input guard design.

`corpus.unique_count` — число review rows до canonical dedup. Три записи с разными
source IDs, но одинаковыми author/date/score/text дают `unique_count=3` и
`selected_count=1`. Worker использует первое число и отправляет запрос с одним
отзывом, обходя детерминированное правило «меньше трёх — insufficient_data без
provider call». В mock ответе `ok` такой job публикует summary как успешный.

Probe `test_21`: 3 collected / 1 distinct input / 1 provider call / `succeeded`.
Порог нужно применять к реальному входу после обязательной дедупликации. Это не
предложение вводить новую семантическую эвристику содержательности: её оценка при
достаточном входе по принятому контракту остаётся у модели.

### R19 — P2: некорректная оценка одной игры обрывает весь scheduler tick

Код: [parser.py:128](../../app/metacritic/parser.py#L128),
[runner.py:71](../../app/processing/runner.py#L71),
[scheduler.py:76](../../app/processing/scheduler.py#L76).
Связь: IMP-02/03 / HRD-01, `NFR-02/04/05`, `AC-NFR-02/04/05`.

Parser принимает целочисленный Metascore вне 0–100. PostgreSQL правильно отклоняет
его check constraint, но `process_candidate` не классифицирует эту ошибку.
Исключение выходит из `run_tick`, непрерывный scheduler тоже не перехватывает его.
Run остаётся `running`, текущий candidate — `processing`, следующая исправная
игра партии — `pending`. Это подтверждает отсутствие изоляции ошибки данных
одной игры; целостность таблицы сама по себе не обеспечивает изоляцию pipeline.

Probe `test_22`: реальный `_parse_platform` возвращает 101, а интеграционный
batch из двух игр завершается исключением с указанными состояниями. Нужны
validation диапазонов/границ DTO до записи, классификация ожидаемых source-data
ошибок и корректное завершение run при неожиданном исключении.

### R20 — P2: core retry не соблюдает принятый максимум пяти попыток

Код: [runner.py:63](../../app/processing/runner.py#L63),
[selector.py:92](../../app/processing/selector.py#L92);
контракт: [design.md:76](../../docs/design.md#L76).
Связь: IMP-03 / HRD-02, `NFR-02`, `R-TIM-01/02`.

После любой classified core failure кандидат остаётся `retryable`, независимо
от `attempt_count`. Selector снова берёт его первым. Probe `test_23` делает семь
почасовых запусков в один день: `attempt_count=7`, `state=retryable`, хотя design
ограничивает автоматические попытки пятью. При 20 постоянно ошибочных первых
играх retry-first заполняет всю партию и блокирует новые игры до смены дня.
Нужен terminal `failed` после принятого лимита и определённый reopen path.

### R21 — P2: UI скрывает сохранённое видео без embedUrl

Код: [queries.py:99](../../app/catalog/queries.py#L99),
[game_detail.html:25](../../app/presentation/templates/presentation/game_detail.html#L25).
Связь: IMP-02/05, `DATA-02`, `UI-02`, `AC-DATA-03`, `AC-UI-02`.

Parser и модель поддерживают `video_content_url`, но detail query передаёт только
`video_embed_url`. Для сохранённого `contentUrl` без `embedUrl` карточка выводит
`No data` и не показывает существующую ссылку. Нужен fallback на валидный content URL.
Probe `test_24`: HTTP 200, content URL есть в БД, ссылки на трейлер в HTML нет.

## Ранее известные замечания, повторно подтверждённые на текущем SHA

### R01 — P1: отсутствует preflight полного AI payload

[corpus.py:186](../../app/reviews/corpus.py#L186) считает review slices + 64,
[worker.py:138](../../app/summaries/worker.py#L138) резервирует фиксированные 6,800,
но не проверяет полный `messages + response_format` перед HTTP. JSON escaping,
system prompt, schema и framing увеличивают вход. Probe `test_13`: десять slices
по 450 токенов отправлены через реальный adapter в MockTransport; полная оценка
по принятой формуле равна **19,060 при лимите 6,000**. Это локальная оценка,
а не измерение фактического тарифицируемого usage Groq. Нужен guard exact payload
и reservation на его основе. Связь: IMP-04, AI-01/02, R-AI-02.

### R03 — P1: неизменный повторный сбор становится unstable

[collector.py:199](../../app/reviews/collector.py#L199) увеличивает `unique_count`
только при создании глобально новой text version. Существующий Review, впервые
наблюдаемый в новой collection, ошибочно считается дублем текущего обхода.
Probe `test_02`: на следующий день три observations, `unique_count=0`,
`unstable`. Считать нужно уникальные observations конкретной generation.
Связь: IMP-04, AI-03, AC-AI-05, NFR-04.

### R04 — P1: изменение текста/оценки не обновляет правильный вход

[corpus.py:124](../../app/reviews/corpus.py#L124) хеширует только identity keys,
не версии/содержимое. Изменившиеся тексты со стабильными IDs возвращают прежний
корпус и старый model input (`test_03`). Дополнительно score/date/author находятся
в `get_or_create(defaults=...)`; score-only изменение при прежнем тексте не
сохраняется: новые source scores 1 остаются 8 в observations (`test_15`).
Нужно определить полную immutable version и fingerprint точного snapshot.
Связь: IMP-04, AI-03, AC-AI-05, NFR-04.

### R05 — P1: corpus смешивает законченный и незавершённый обходы

[corpus.py:33](../../app/reviews/corpus.py#L33) находит любой последний terminal
job, а [строка 81](../../app/reviews/corpus.py#L81) выбирает все несуперседированные
Reviews платформы независимо от observations этого job. Probe `test_04`:
pending collection добавляет четвёртый отзыв в corpus с `reported_count=3`.
Нужно строить только из выбранных terminal generation observations с явной
политикой текущего набора routes; существующая история не является текущим snapshot.
Связь: IMP-04, AI-01/02, NFR-04.

### R06 — P1: crash после collection commit теряет задание summary

[collector.py:259](../../app/reviews/collector.py#L259) завершает collection,
а corpus/summary handoff вызывается после транзакции. Probe `test_05` падает
в этой точке: job=`complete`, corpora/summary jobs отсутствуют, обычный reclaim
не находит работы даже на следующий день. Нужен durable handoff intent либо
идемпотентная reconciliation законченных collections. Связь: IMP-04, AI-01/02,
NFR-01/02.

### R07 — P1: unsupported AI output публикуется как succeeded

[worker.py:245](../../app/summaries/worker.py#L245) молча пропускает claim, если
support ID отсутствует в input; validator проверяет форму, но не принадлежность
ID. Probe `test_07`: ответ со ссылкой R99 принимается, job=`succeeded`, claims=0.
Нужна проверка всех supports до атомарной публикации с retryable malformed output.
Связь: IMP-04, AI-01/02, AC-AI-01/02.

| ID / приоритет | Место, подтверждённый эффект и нужное исправление | Probe / связь |
|---|---|---|
| R08 / P2 | [collector.py:157](../../app/reviews/collector.py#L157): успешные страницы тратят retry budget; пять успешных страниц + первый fetch failure сразу дают `failed`. Разделить page/HTTP history и лимит повторов текущей ошибки | `test_06`; IMP-04, NFR-02/04, AC-AI-06 |
| R09 / P2 | [worker.py:117](../../app/summaries/worker.py#L117), [quota.py:28](../../app/summaries/quota.py#L28): capacity read и reservation insert не атомарны. Два соединения допускают 13,600 reserved tokens при TPM=8,000. Нужен сериализованный admission вместе с reservation | `test_16`; IMP-04, NFR-03, R-AI-02 |
| R10 / P2 | [groq_adapter.py:137](../../app/summaries/groq_adapter.py#L137), [worker.py:50](../../app/summaries/worker.py#L50): четыре HTTP calls принадлежат одной attempt/reservation; после crash/reclaim старая attempt остаётся без outcome/completed_at. Каждая фактическая попытка требует своей записи и terminal lifecycle | `test_11`, `test_18`; IMP-04, NFR-02/05, R-AI-02 |
| R11 / P2 | [collector.py:81](../../app/reviews/collector.py#L81): ownership проверяет только token, без running/generation/cursor state. Повторная доставка того же claim делает второй HTTP и портит `complete → unstable`. Нужна проверка принятой страницы до HTTP и fencing всех переходов | `test_10`; IMP-04, NFR-03 |
| R12 / P2 | [presentation/summaries.py:81](../../app/presentation/summaries.py#L81): pending collection не учитывается, старый результат показан `ok`; одинаковые `created_at` выбирают старый corpus. Учитывать текущую collection и задать полный deterministic ordering | `test_08`, `test_09`; IMP-05, UI-02, AC-UI-02/06 |
| R13 / P2 | [contour.py:164](../../app/summaries/contour.py#L164): `status=[]` вызывает TypeError при membership в set. Исключение не превращается в retryable, непрерывный worker может остановиться. Валидировать типы до операций, требующих hashable value | `test_14`; IMP-04, AC-AI-06, NFR-02/04 |
| R14 / P2 | [run_worker.py:67](../../app/reviews/management/commands/run_worker.py#L67): после любого collection tick следует return; ready summary не рассматривается, пока collection queue доступна. 30 успешных страниц, free quota, 0 summary attempts. Нужна справедливая очередь двух типов работ | `test_12`; IMP-04, AI-01/02, R-AI-02 |

## Подтверждённые исправления и сильные стороны

- **R02 исправлен:** исходный counterexample теперь даёт batches `[1,20,20,8,0]`,
  все 49 игр, без потери хвостов terminal/nonterminal страниц (`test_01`).
- **R15 исправлен:** повторяющаяся nonterminal страница останавливается после
  двух запросов с `browse_repeated_page`; искусственная аварийная отсечка не
  достигается (`test_17`). Все 11 новых discovery regression tests проходят
  в локальном и Linux наборах. Новых material findings в самом изменении
  discovery этого коммита не обнаружено. R16/R20 относятся к прежнему core lifecycle.
- Django/PostgreSQL и разделение catalog/processing/reviews/summaries/presentation
  соответствуют масштабу задачи; отдельная дополнительная инфраструктура для
  очередей сейчас не требуется для устранения найденных дефектов.
- Есть реальные constraints, миграции, immutable corpus/items, фиксация prompt/schema,
  frozen selection oracle и воспроизводимые проверки. Поиск/фильтр/порядок/null
  покрыты тестами; локальный путь source data in DB → read-only web работает.
- Контейнерная correction подтверждается новой сборкой, Linux проверками и
  HTTP/CSS smoke. Web использует отдельную роль только для чтения; DB не
  публикуется наружу production override; логи скрывают exception payloads.

## Оценка полноты и процесса

| Область | Вывод на проверенный SHA |
|---|---|
| Baseline / G1–G3 | Артефакты и offline planning checks существуют и проходят. Это обоснование baseline, не доказательство готовности runtime |
| IMP-01/02 | Локальная сборка и card path подтверждены повторно. Текущее hosted/public evidence в этой сессии не получено |
| IMP-03 | Исправление discovery корректно на проверенных сценариях; core fencing/retry ещё имеют R16/R20 |
| IMP-04 | Основной функционал есть, но collection snapshots, обновление, handoff, AI limits/validation и очередь имеют material defects |
| IMP-05 | Основной каталог работает; freshness/cache/video display требуют исправления |
| Similarity | Обязательная функция ещё не реализована; SIM-EVAL-01 Ready, дальнейшие задачи Planned. Это открытый Must, а не найденная регрессия |
| HRD / G4–G6 | Full E2E, hardening, capacity, public operational evidence не завершены; штатные тесты их не заменяют |
| Deployment | Compose не содержит постоянных scheduler/worker services; HTTPS и эксплуатационные проверки ещё впереди, как и указано в README/PUB tasks |
| Delivery / G7 | Пакет приёмки, архив AI-переписки и финальная внешняя проверка ещё не закрыты |

Текущие `Changes requested` у IMP-02–05 и незакрытые G4–G7 соответствуют
найденному состоянию. Исторические документы с формулировками «закрыт» следует
читать только как датированные свидетельства: наличие 177 зелёных тестов и
прохождение frozen selection oracle не доказывают snapshot/attempt/queue контракты.
В частности, часть corpus/worker tests создаёт уже готовые модели вручную и не
проводит через сборщик повторный полный день; из-за этого они обходят R03–R06.
Проверка чистого selector на frozen oracle не проверяет, правильный ли pool
передал ему production corpus builder.

## Очередь исправлений

Это scope и проверяемые исходы последовательных correction-циклов существующих
IMP-задач, а не новые task IDs или обход зависимостей. Текущий приоритет и статусы
назначает [action_plan.md](../../action_plan.md). В каждом цикле: author →
adversarial review → проверка → focused commit → стоп. Связанные модули могут
меняться в рамках одной coherent correction; задача-владелец указана ниже.

| Порядок / задача-владелец | Findings / исходные probes | Exit criteria correction |
|---|---|---|
| 1. IMP-04: collection/snapshot/handoff | R03–R06; `test_02/03/04/05/15` | Два одинаковых дня завершаются корректно без новых text versions; text/metadata edit создаёт точный новый snapshot; удалённые и partial reviews не входят в текущий corpus; fingerprints отражают snapshot и exact input; crash до/после terminal commit не теряет corpus/summary intent; правильные исходы проверены через collector, а не только вручную созданные модели |
| 2. IMP-03: core ownership/retry | R16/R20; `test_19/23` | Старый owner не меняет candidate ни до HTTP, ни при применении/recovery; один successful core commit на игру/день; после пяти автоматических ошибок candidate=`failed`, следующая новая игра может быть выбрана; reopen и restart не обходят лимит |
| 3. IMP-02: source validation/failure isolation | R19; `test_22`; затрагивает processing | Некорректные score/DTO границы классифицируются до записи; остальные игры партии продолжаются; ошибка оставляет terminal run с точными counters/error, а не вечный `running`; предыдущие хорошие значения сохраняются |
| 4. IMP-04: payload/quota/attempts | R01/R09/R10; `test_13/16/11/18` | Exact canonical payload проходит принятый 6,000-token preflight до HTTP; reservation атомарна с admission; два worker не превышают квоту; каждому реальному HTTP соответствует отдельная attempt; reclaim завершает старую attempt как abandoned, late response не переписывает terminal outcome |
| 5. IMP-04: input/output validation | R07/R13/R18; `test_07/14/21` | Все support IDs принадлежат exact input; malformed JSON types дают classified retry без остановки worker; недостаточный вход после dedup завершается insufficient_data без provider call; неподтверждённый output не публикуется |
| 6. IMP-04: collection retry/redelivery | R08/R11; `test_06/10` | Успешные страницы не тратят retry budget ошибки; accepted claim нельзя повторно применить или отправить по HTTP; проверяются generation/cursor/state/token и единственность принятой страницы |
| 7. IMP-04: worker fairness | R14; `test_12` | При одновременно доступных collection и summary jobs оба типа получают ограниченное время ожидания; свободная quota позволяет summary прогрессировать до полного осушения collection queue |
| 8. IMP-05: freshness/cache/video | R12/R17/R21; `test_08/09/20/24`; затрагивает summaries/catalog | Pending/error collection честно помечает предыдущий результат stale; ordering имеет tie-breaker; тот же input/contour на новом corpus показывает готовый cache hit с актуальными coverage counters; content URL виден без embed URL |

Все 19 открытых findings назначены ровно одному основному correction-циклу.
Пересечения IMP-02/03/04/05 отражены в task evidence tracker; они не означают
дублирование работы. При исправлении archived defect probes переводятся в
desired-outcome application regressions. Полный штатный suite и затронутые
acceptance checks выполняются перед commit; исторический probe остаётся evidence
поведения `6551e42` и не должен требовать сохранения дефекта.

Hosted CI/public evidence соответствующего SHA, similarity, E2E и HRD/PUB/REL
продолжаются по зависимостям master tracker. Ни этот отчёт, ни локальная correction
не закрывают эти gates и не меняют frozen oracles или принятые thresholds.

## Проверка публикации ревью

После переноса evidence в Git-пути повторно выполнен
`python -B research/reviews/6551e42/reproduce.py`: 24 probes, OK; все 24 observations
совпали с сохранённым исходным результатом. Diff исходного и опубликованного
harness содержит только путь команды и вычисление repository root, без изменения
assertions. `research/planning/check_plan.py` и его 18 unit tests прошли; сохранены
46 Task IDs, девять gate IDs, 28 Must и прежний граф зависимостей.

Adversarial self-review публикации проверил распределение всех 19 findings ровно
по одному основному циклу, различие defect probes и acceptance regressions,
границы local/hosted evidence и отсутствие преждевременного Verified. Проверены
локальные ссылки, UTF-8/LF, `git diff --check` и известные token patterns в
публикуемых файлах. Это проверка данного documentation/evidence change; новых
runtime исправлений, повторной полной deployment-проверки или secret scan всей
истории эта публикация не заявляет.
