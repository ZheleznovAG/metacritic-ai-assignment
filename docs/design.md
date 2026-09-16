# Внутренние контракты и модель данных

- **Статус:** Verified design — retry/storage/evidence correction проверена; application capacity и quality policies не считаются доказанными
- **Дата:** 2026-09-09 (Asia/Novosibirsk; корректировка baseline 0.18)
- **Задача:** `PLN-02`
- **Архитектура:** [`ADR-0001`](decisions/0001-minimal-stack-and-architecture.md)
- **Связи:** `RUN-01`, `SEL-01–SEL-03`, `DATA-01–DATA-03`, `AI-01–AI-03`, `UI-01–UI-05`, `SIM-01–SIM-03`, `NFR-01–NFR-06`

## Область решения

Документ задаёт тестируемые границы модулей, состояние PostgreSQL, транзакции и инварианты. Это логическая схема для будущих Django migrations, а не реализация.

Расширение для Bonus 2 вынесено в отдельный [Candidate-контракт](bonus2_design.md): мониторинг процессов и защищённые manual requests. Его технические решения принимаются по evidence `BON-21`/`BON-22`; они не меняют этот принятый Must-контракт одним фактом планирования.

Must-контур использует только уже выбранные Django, PostgreSQL и три application processes внутри Compose: `web`, `scheduler`, `worker`. `worker` последовательно выполняет два вида сохранённой enrichment-работы: получение отзывов и AI-суммаризацию. Redis, Celery, отдельный search/vector store, object storage, event bus и новый monitoring service не добавляются.

## Сквозной поток

```text
UTC hourly slot
  -> core selection and Game/GamePlatform commit
  -> ReviewCollectionJob
  -> platform-specific review pages until a complete collection snapshot
  -> immutable Review text versions + observations
  -> immutable bounded ReviewCorpus
  -> SummaryJob
  -> SummaryAttempt using an identified model/configuration
  -> validated ReviewSummary + grounded SummaryClaims
  -> read-only game card
```

Core commit не ждёт отзывов или модели. Ошибка review route или Groq меняет только enrichment state и остаётся доступной для retry; сохранённая игра и дневной progress не откатываются.

## Границы модулей

| Модуль | Ответственность | Не делает |
|---|---|---|
| `catalog` | Identity игры/платформ, non-destructive upsert, source fields и aliases | Не решает порядок дня и не вызывает AI |
| `processing` | UTC slots, daily cycle, batch до 20, lease/fencing, attempts и run counters | Не разбирает HTML и не содержит UI rules |
| `metacritic` | HTTP/parse adapter, typed DTO, `SourceFetch` evidence и классифицированные ошибки | Не пишет domain rows напрямую и не исправляет source semantics |
| `reviews` | Сохраняет скачанные review records/observations, строит audience corpus | Не переводит, не пересказывает и не удаляет историю при partial fetch |
| `summaries` | Persistent jobs, provider adapter, attempts, canonical validation и claims | Не смешивает аудитории и не знает HTML/UI |
| `similarity` | Версионированный объяснимый ranking по сохранённым признакам | Не вызывает внешнюю модель и не требует vector DB |
| `presentation` | Read-only list/detail queries и Django templates | Не запускает ingestion/enrichment через публичный Must UI |
| `observability` | Structured events и представление persistent run/job state | Не является отдельным storage/monitoring service |

Django ORM используется прямо внутри application services; универсальный repository layer не вводится. Протоколами изолируются только изменяемые границы: время, Metacritic и AI provider.

## Логическая модель PostgreSQL

Все surrogate primary keys внутренние. Все timestamps timezone-aware и сохраняются в UTC. Enum/check constraints ниже являются частью schema contract, а не только Python validation.

### Каталог и provenance

| Таблица | Ключевые данные | Обязательные ограничения |
|---|---|---|
| `game` | `source`, `source_game_id`, current locator, title, cover URL, developer, description, video URL, `genres` (ordered normalized names), `genres_last_changed_fetch_id`, `last_changed_fetch_id`, timestamps | `UNIQUE(source, source_game_id)`; обязательны identity/title/locator; source text хранится без перевода |
| `game_alias` | `game_id`, source locator, first/last seen UTC | `UNIQUE(source, locator)`; alias другого game вызывает conflict, не merge |
| `game_platform` | `game_id`, `source_platform_id`, `source_game_platform_id`, slug/name, Metascore, Userscore, critic/user route, `metascore_last_changed_fetch_id`, `userscore_last_changed_fetch_id` | `UNIQUE(game_id, source_platform_id)` и `UNIQUE(source, source_game_platform_id)`; score ranges; `null` не равен нулю |
| `source_fetch` | owning run или review job, kind, collection generation nullable, allowlisted URL, cursor/offset, page ordinal, attempt number, fencing token, reported total, item count, started/completed UTC, HTTP status, response SHA-256, parser contract version, outcome/error code | Ровно один owner; review attempt требует non-null generation/page/attempt и `attempt_no > 0`; `UNIQUE(review_job_id, collection_generation, page_ordinal, attempt_no)`; отдельная partial unique constraint на `(review_job_id, collection_generation, page_ordinal)` только для `outcome IN ('succeeded', 'empty')`; полный HTML, cookies и authorization headers не сохраняются |

`last_changed_fetch_id` указывает на fetch, из которого принято текущее значение. Failed/structurally invalid fetch создаёт evidence, но не меняет хорошее поле. Отсутствовавшая в partial response платформа не удаляется.

Для каждой платформенной оценки provenance хранится отдельно. Если новый успешный
ответ содержит `null`, а non-destructive merge сохраняет прежнюю оценку (включая
ноль), её ссылка на источник также сохраняется. Принятая числовая оценка или
подтверждённое отсутствие при отсутствии старого значения указывает на текущий
успешный fetch: detail для Metascore/lead Userscore, platform fetch для остальных
Userscore. Ранее неверно перемещённые ссылки автоматически не реконструируются.

`source_fetch` представляет одну фактическую попытку HTTP-запроса. Worker под row lock job выделяет следующий `attempt_no`, сохраняет `started` и текущий fencing token до внешнего вызова. Допустим один переход в terminal `succeeded/empty/failed/invalid/abandoned/superseded`; terminal запись не переписывается. Failed/invalid attempt не занимает ключ успешно принятой страницы: retry той же generation/page получает новый номер и сохраняет прежнюю ошибку. При reclaim незавершённая попытка становится `abandoned`; поздний ответ не переоткрывает её. Если владение потеряно до применения ответа, ещё открытая попытка завершается как `superseded` без observations и cursor update.

Принятие страницы под row lock проверяет job generation, ожидаемый cursor/page и fencing token, затем одной транзакцией сохраняет reviews/observations, terminal success и следующий cursor. Partial unique constraint допускает только одну принятую страницу. Повторная доставка уже принятого page не делает HTTP-вызов и не продвигает cursor повторно. Изолированный PostgreSQL probe ограничений и rollback-сценария: [`pln02_review_attempts.sql`](../research/feasibility/probes/pln02_review_attempts.sql); реальные worker/concurrency tests остаются у `IMP-04/HRD-03`.

### Почасовая обработка

| Таблица | Ключевые данные | Обязательные ограничения |
|---|---|---|
| `processing_lease` | singleton resource `ingestion`, monotonic fencing token, owner run, expiry/heartbeat UTC | Один действующий owner; новый token делает старые commits недействительными |
| `daily_cycle` | business date/timezone, phase, browse page/offset checkpoint, exhausted flag | `UNIQUE(business_date, timezone)`; phase: `new_releases_pending/browse/exhausted` |
| `processing_run` | unique trigger key, scheduled slot UTC, business day snapshot, status, start/end, counters, error code | `UNIQUE(trigger_key)`; один scheduled key вида `scheduled:<UTC-hour>` не создаёт повторную работу |
| `daily_candidate` | cycle/game, immutable source order, state, next retry UTC, last error | `UNIQUE(cycle_id, game_id)` и `UNIQUE(cycle_id, source_order)`; `pending/processing/processed/retryable/failed` |
| `core_attempt` | candidate/run, attempt number, fencing token, start/end, outcome/error | `UNIQUE(candidate_id, attempt_no)`; success допустим только при текущем fencing token |

Scheduler проверяет текущий UTC slot не реже раза в минуту. Restart в том же часу переиспользует trigger key; прошедший час без run фиксируется как наблюдаемый gap, но не создаёт burst из старых batch. Global lease TTL — 45 минут с heartbeat; core candidate имеет не более пяти автоматических attempts и остаётся видимым/reopenable после `failed`.

Core claim, recovery и применение ответа проверяют token, owner run и expiry под блокировкой singleton lease до изменения кандидата. Claim перечитывает candidate под row lock и допускает только pending/retryable; создание незавершённой CoreAttempt и увеличение attempt count коммитятся до HTTP. Recovery нового owner закрывает прерванные попытки как failed/interrupted и не трогает попытки своего действующего token. Пять начатых попыток исчерпывают дневной бюджет, включая crashes; failed job освобождает место новым играм. Изменение state/counter вручную не сбрасывает сохранённую историю attempts. Обычный новый business day получает новый candidate с новым бюджетом; инструмент сброса попыток внутри дня не предоставляется. После expiry текущий run прекращает запись, даже если следующая lease ещё не получена.

Identity check, non-destructive Game/GamePlatform upsert, закрытие `core_attempt`, перевод candidate в `processed` и создание идемпотентных `review_collection_job` для известных routes выполняются одной транзакцией. Сетевое получение отзывов и AI-вызовы выполняются worker после commit и не входят в лимит 20. Crash до commit откатывает и core success, и задания; crash после commit оставляет задания доступными worker. При ошибке записи задания транзакция повторяется целиком: состояния «processed, но задание потеряно» нет.

SEE ALL checkpoint хранит первую ещё не полностью принятую страницу. Если партия
заполнена посреди страницы, следующий запуск повторно читает эту же страницу,
пропускает уже сохранённые daily identities и выбирает оставшийся хвост в source
order. Дубликаты внутри ответа также пропускаются. Только сохранение всех новых
identities страницы позволяет атомарно продвинуть checkpoint; `has_next_page=False`
переводит цикл в `exhausted` лишь после принятия всего хвоста. Pending/retryable
candidates занимают места в следующей партии до новых identities; общий лимит — 20.

Один SEE ALL scan начинает не более 100 запросов и не начинает новый запрос после
60 секунд monotonic elapsed time. Уже полученная страница сохраняется; это deadline
допуска следующего запроса, а не принудительное прерывание HTTP/DB/core обработки.
Повтор набора identities любой ранее прочитанной в этом scan страницы (включая
перестановку) или пустая nonterminal страница останавливает scan без перехода через
проблемную страницу. Различающиеся страницы, состоящие только из известных игр,
разрешено проходить до этих границ. Остановка сохраняет `browse` и checkpoint,
публикует `browse_repeated_page/browse_empty_page/browse_page_limit/browse_time_limit`
в `ProcessingRun.error_code`; run — `partial` при успешной core работе, иначе `failed`.
Следующий час продолжает с checkpoint. Эти границы не означают source exhaustion
и не доказывают дневную capacity. Внешний изменяемый список не становится snapshot:
вставки/удаления между повторными чтениями могут сдвинуть позиции; известное
ограничение `SPK-04` сохраняется. Проверки: [discovery correction](requirements/imp_03_discovery_correction.md).

### Скачанные отзывы и точный AI input

| Таблица | Ключевые данные | Обязательные ограничения |
|---|---|---|
| `review_collection_job` | game/platform/audience, collection generation, source order/filter/limit, state, next allowlisted URL/cursor, reported/fetched/unique/duplicate/page counters, visited-cursor fingerprint set, started/completed UTC, attempt count, available/lease timestamps, last error | `UNIQUE(daily_candidate_id, game_platform_id, audience)`; audience только `critic/user`; state `pending/running/complete/empty/retryable/unstable/failed`; cursor продвигается только с durable page commit |
| `review` | game/platform/audience, source review ID если есть, deterministic identity key, author/source label, score/date labels, `text_original`, content SHA-256, version SHA-256, `first_seen_at`, optional `supersedes_review_id` | Текст и metadata после insert неизменяемы; `UNIQUE(game_platform_id, audience, identity_key, version_sha256)`; last seen выводится из observations |
| `review_observation` | collection job/generation, successful `source_fetch_id`, `review_id`, page и route-global source positions | `UNIQUE(source_fetch_id, page_position)`, `UNIQUE(collection_job_id, collection_generation, review_id)` и `UNIQUE(collection_job_id, collection_generation, route_global_position)`; задаёт точный состав и порядок page/route snapshot, не запрещая наблюдать review в следующей generation |
| `review_corpus` | game/audience, candidate policy version, source-set fingerprint, model-input fingerprint, created UTC, complete/empty route counts, reported/fetched/unique/deduplicated/selected review counts, tokenizer/version, raw/guarded prompt token counts, completion reservation | `UNIQUE(game_id, audience, policy_version, source_set_fingerprint)`; corpus после создания неизменяем; создаётся только из complete/empty snapshots всех известных routes аудитории |
| `review_corpus_item` | corpus, ordinal, prompt review ID, `review_id`, exact `input_text`, input token count, SHA-256, truncation flag | Отдельные `UNIQUE(corpus_id, ordinal)`, `UNIQUE(corpus_id, prompt_review_id)` и `UNIQUE(corpus_id, review_id)`; support может ссылаться только на item этого corpus; text заканчивается на token boundary |

`text_original` — весь plain text каждого реально полученного review card после единственной механической нормализации: HTML decode, trim и collapse whitespace. Язык, формулировка и смысл не меняются. Текст хранится даже если не попал в ограниченный model input. Полный HTML страницы не хранится; его SHA-256 и extraction metadata находятся в `source_fetch`.

Если Metacritic отдаёт стабильный review ID, `identity_key=id:<value>`. Иначе используется `fallback:<SHA-256>` от audience, platform ID, source review URL, author/source label, published label, score и полного нормализованного текста. `content_sha256` остаётся хешем только нормализованного текста. `version_sha256` — SHA-256 canonical JSON `{version:1,text,author,score,date}` с сохранением различия null/пустой label. Изменение текста или любого из этих labels со стабильным ID создаёт новую immutable version и optional `supersedes` link на ранее сохранённую версию; без стабильного ID система не заявляет, что две разные версии — один логический отзыв. Возврат A→B→A повторно использует сохранённую A. Состав текущего snapshot определяется observations, а не обратной связью `superseded_by`.

Для каждого известного platform/audience route collection job создаёт новую generation и начинает с подтверждённой backend-ссылки из SSR state. Web query `?page=N` не используется: проверка показала, что он возвращает первый segment повторно. После allowlist-проверки route identity worker следует только `links.next.href`, сохраняет каждую страницу и все её records, затем атомарно с page commit продвигает cursor. Один worker claim обрабатывает одну страницу, поэтому route из 32 и более pages не держится целиком в памяти и не требует новой очереди или сервиса. Глобальный source maximum неизвестен: total искусственно не обрезается; рабочая память обработки page ограничена её размером, а visited cursors и history хранятся в БД.

Storage состоит из `V` уникальных content versions с суммарным размером текста `T`, `H` observations по всем generations, `A` fetch attempts и `C` corpus/summary records: ориентир `O(T + V + H + A + C)` плюс индексы, WAL и backup. При неизменных `N` отзывах и `D` полных обходах сохраняются `N` text versions, но `N × D` observations. Дедупликация текста не ограничивает рост истории. Фактические bytes/row, text sizes, indexes/WAL, свободное место и горизонт хранения измеряются в `HRD-05/PUB-02` на PostgreSQL; до этого 80 GB VDS не считается доказанной storage capacity. Автоматическое удаление исходных отзывов не принято; нехватка места требует остановки новой загрузки с диагностируемым состоянием и пересмотра retention/capacity, а не скрытого удаления history.

Collection generation становится `complete`, только если `next` отсутствует, `totalResults` был стабилен на всех pages, каждый page завершён успешно, unresolved duplicates нет и unique fetched count равен reported total. Unique count считается по identity observations текущего job/generation, независимо от того, была ли Review version сохранена вчера; duplicate count равен fetched minus unique. Валидный нулевой total без полученных records даёт `empty`. Cursor loop, повтор ordered page identities, изменение route parameters/total, смена версии одного identity внутри обхода или расхождение counts дают `unstable`; транспортная ошибка — `retryable/failed`. Незавершённая generation не смешивается с предыдущей и не запускает summary. Прошлые observations и опубликованный summary сохраняются со stale-причиной до появления нового полного snapshot. Датированный внешний evidence и точные acceptance rules находятся в [`research/feasibility/metacritic-contract.md`](../research/feasibility/metacritic-contract.md) и [`reviews-pagination.json`](../research/feasibility/fixtures/metacritic/reviews-pagination.json).

Terminal page, observations/counters, corpus/items и создание либо повторное использование summary job коммитятся одной транзакцией. Ошибка handoff откатывает terminal page к предыдущему checkpoint; обычный reclaim истёкшей lease повторяет страницу. После commit summary intent уже durable, даже если worker сразу завершился. HTTP выполняется до транзакции. Порядок locks у collection commit: Game → ReviewCollectionJob; corpus builder тоже блокирует Game. Это сериализует запись платформ одной игры и создание corpus; core upsert записывает Game до платформ и review jobs. Отдельный вызов builder атомарно сохраняет corpus, а гарантия handoff принадлежит вызывающей транзакции collector.

Corpus для одной игры и ровно одной аудитории строится детерминированно:

1. Текущий дневной набор задаёт последний `processed` DailyCandidate игры по `(business_date,id)`, независимо от времени завершения отдельных routes. Все известные routes аудитории должны иметь job именно этого candidate, terminal generation (`complete` или `empty`), отсутствующий next cursor и согласованные counts без дублей. При missing/pending/running/retryable/unstable/failed route новый corpus не создаётся. Берутся только observations этой generation с successful SourceFetch того же job/generation; их число и уникальные identities должны совпасть с counters. Поздно завершившийся старый день, неполный новый обход, удалённые отзывы и прежние generations не добавляют records из истории.
2. Точные cross-platform повторы удаляются по canonical JSON fingerprint нормализованных author/date/score/text. Одинаковый source ID на двух платформах сам по себе не доказывает duplicate: только такие коллизии передаются selector как `platform:` плюс canonical JSON `[source_platform_id,identity_key]`. Остальные identity/hash inputs остаются прежними. Selected item сохраняет FK версии именно выбранной платформы.
3. Candidate selection `1.0.0-candidate` не берёт только первую/последнюю source page: внутри каждой платформы records сортируются по SHA-256 от policy version и review identity, затем платформы чередуются round-robin по стабильному `platform_slug`, который передаётся в selection pool. Так любой объём хранится полностью, а bounded sample воспроизводимо распределён по полному snapshot; репрезентативность этого правила остаётся quality-кандидатом. `REV-EVAL-01` сначала замораживает corpus examples, metric, threshold и hard invariants, `IMP-04` затем сравнивает candidate с более простым baseline без изменения oracle, а `HRD-04` проверяет финальную регрессию.
4. В model input входит не более 10 reviews. Полный сохранённый текст не обрезается; каждый exact input slice ограничивается первыми 450 токенами `o200k_harmony` и записывается с `input_token_count`/`was_truncated`. Character/byte counts разрешены только как диагностика, не как budget guard.
5. `source_set_fingerprint` — SHA-256 canonical JSON `{snapshot_version:2,routes:[...]}`: routes упорядочены по source platform ID и содержат ID/slug, terminal state, reported/fetched counts и отсортированные `{identity,version}` всех наблюдаемых reviews. Дата, job/DB IDs и порядок страниц не входят в fingerprint; неизменный повторный день повторно использует corpus. Изменение версии вне sample и добавление empty route меняют fingerprint. Prompt IDs назначаются после selection как `R01…R10`. `input_fingerprint` — SHA-256 canonical JSON из game identity, audience, policy/tokenizer versions и ordered `{id,text}`. Изменение данных вне выбранного input меняет source-set fingerprint, но само по себе не расходует AI quota.
6. Preflight токенизирует весь exact canonical `messages + response_format`, добавляет 64 токена guard для provider framing и допускает не более 6,000 estimated prompt tokens. Вместе с `max_completion_tokens=800` reservation не превышает 6,800 токенов — на 1,200 ниже Free Plan `8,000 TPM`. Tokenizer/версия, raw count, guard и reservation входят в corpus/attempt provenance.

`o200k_harmony` выбран потому, что это tokenizer семейства `gpt-oss`; используемая библиотека фиксируется отдельно. Production-maximum multilingual case (10 × 450 input tokens) дал local estimate `5,559`, reservation `6,359` и live Groq usage `5,493` prompt / `240` completion / `5,733` total. Проверка воспроизводится [`check_token_budget.py`](../evals/reviews/check_token_budget.py), sanitised результат сохранён в [`token-budget-report.json`](../evals/reviews/token-budget-report.json). Если tokenizer недоступен, request превышает budget либо provider usage выходит за guarded estimate, вызов не отправляется/следующие вызовы приостанавливаются с явной configuration error; молчаливого character fallback нет.

Если доступно меньше трёх записей, job завершается `insufficient_data` детерминированно без provider call. При трёх и более records окончательное решение о содержательности остаётся частью прошедшего prompt/schema contract: общие оценки без наблюдения могут дать `insufficient_data`.

### AI jobs, attempts и summaries

`reviews.ReviewCorpusHead` хранит один текущий corpus для game/audience и checkpoint
последнего проверенного collection cohort. Builder обновляет head под Game lock
в той же транзакции, включая возврат к старому cached corpus. Checkpoint содержит
current processed candidate, route identity/path, generation/page/cursor/state и
counts. Он не меняет immutable corpus или исходный summary provenance. UI читает
только этот лёгкий checkpoint и проверяет его против текущих routes/jobs;
отсутствующий или несовпадающий head означает stale. Legacy heads автоматически
не выдумываются: их создаёт обычный успешный build после проверки observations.

| Таблица | Ключевые данные | Обязательные ограничения |
|---|---|---|
| `summary_job` | game/audience, source corpus, input fingerprint, contour fingerprint, state, attempts, available/lease UTC, last safe error | `UNIQUE(game_id, audience, input_fingerprint, contour_fingerprint)`; неизменный input/config является cache hit |
| `summary_attempt` | job/attempt, provider/API, requested model, optional returned model/provider system fingerprint, prompt/schema/preparation/normalizer/adapter/tokenizer versions + hashes, estimated/reserved/actual prompt/completion/total tokens, allowlisted generation parameters, `started_at`/`completed_at` UTC, `latency_ms`, outcome/error | `UNIQUE(job_id, attempt_no)`; после terminal outcome неизменяема; secret, provider request ID, raw reasoning и raw response envelope не сохраняются |
| `review_summary` | job, successful attempt nullable, method `model/rule`, status, `generated_at` UTC, insufficient reason, canonical output fingerprint, normalization notes | `UNIQUE(job_id)`; `ok` требует model attempt, `insufficient_data` не содержит claims |
| `summary_claim` | summary, polarity `like/dislike`, ordinal, claim до 160 chars, supporting corpus item | Не более пяти claims каждого polarity; ровно один support из input corpus; `UNIQUE(summary_id, polarity, ordinal)` |

`contour_fingerprint` вычисляется из provider, API adapter, requested model, prompt, output schema, input-preparation/selection, normalizer и allowlisted parameters. Baseline: Groq Chat Completions, requested model `openai/gpt-oss-20b`, prompt `3.0.0`, schema `2.1.0`, normalizer `1.0.0`, `temperature=0`, `seed=7`, `max_completion_tokens=800`, no tools/reasoning output. Prompt требует summary на основном языке входного корпуса без отдельного перевода. Любое изменение элемента создаёт новый job даже при тех же reviews.

Attempt с requested model, contour и `started_at` коммитится до внешнего вызова. После ответа разрешён единственный переход к terminal outcome с заполнением `returned_model`, `completed_at`, usage/result metadata; после него строка неизменяема. Истёкшая незавершённая попытка закрывается как `abandoned` при reclaim lease, а новый вызов получает следующий `attempt_no`. Поэтому crash между HTTP-вызовом и ответом остаётся видимым и не переписывает историю.

Каждая фактическая попытка фиксирует минимум:

- `provider=groq`, API kind, requested model и фактически returned model;
- provider system fingerprint, только если API его вернул; он не считается immutable model version;
- UTC start/completion, latency и outcome;
- prompt/completion/total tokens и безопасные quota counters, если доступны;
- все версии/hashes контура и exact corpus input fingerprint;
- классифицированный error code без review text, secret или provider request ID.

Provider может не раскрывать immutable revision весов. Поэтому доказуемое утверждение ограничено сохранёнными requested/returned model IDs, optional system fingerprint и полной версией локального контура; придумывать «точную версию модели» нельзя.

Job states: `pending -> running -> succeeded | insufficient_data | retryable | delayed_capacity | failed`. Lease — 5 минут; `SELECT … FOR UPDATE SKIP LOCKED`, fencing token и проверка expiry до admission/commit. После claim worker под transaction advisory lock проверяет ledger и сохраняет reservation одной транзакцией; HTTP выполняется после commit вне DB locks. Rolling token/request limits проверяются для minute/day windows; provider headers уточняют reset/остаток. Без актуального header следующий вызов ждёт минуту. Transport/timeout/5xx используют bounded backoff `1m, 5m, 15m, 1h, 6h`, максимум пять начатых attempts. Adapter не делает скрытых HTTP retries. `429` использует provider reset time и `delayed_capacity`, не включает paid fallback. Malformed/unsupported output становится `retryable`, прошлый опубликованный summary не затирается.

Preflight измеряет canonical messages + schema фактического запроса: максимум 6000 prompt tokens с guard 64 и reserve 800 completion. Tokenizer failure запрещает HTTP; actual usage выше резерва останавливает contour. Attempt хранит hash отправленных canonical bytes, raw/guarded estimate, fencing token и allowlisted rate headers. HTTP timeout 180 секунд ограничивает отдельную I/O phase; просроченная lease запрещает применение ответа.

Summary и claims сохраняются одной транзакцией только после normalizer и canonical validation. Card выбирает job по game/audience/input/current contour, а не по исходному corpus FK. Cache hit сохраняет исходные summary/claim FKs и показывает current coverage из head corpus. Если current input/config или review collection имеет pending/error job, последний валидный результат (generated_at/id) помечается stale с причиной. Для прозрачности рядом доступны returned model ID, `generated_at`, `selected / unique fetched / reported` review counts; исходные отзывы публично не выводятся как часть Must UI.

## Внутренние interfaces

Dispatcher хранит singleton `reviews.EnrichmentTurn` с предпочтением review/summary.
Claim и смена предпочтения коммитятся вместе под row lock; HTTP начинается после
освобождения lock. При двух due очередях каждая получает один из двух последовательных
claims; disabled/not-due очередь уступает второй. Порядок сохраняется после restart.

| Interface | Вход | Результат / error contract |
|---|---|---|
| `Clock.now_utc()` | нет | aware UTC datetime; fake clock в тестах |
| `MetacriticGateway.list_new_releases()` | source contract version | ordered identity DTO + `SourceFetch`; typed unavailable/invalid/identity errors |
| `MetacriticGateway.iter_browse(cursor)` | page/offset cursor | ordered segment + next cursor/exhausted; cursor не меняется при failure |
| `MetacriticGateway.fetch_game(identity)` | confirmed game identity | typed game/platform DTO + provenance; mismatch запрещает save |
| `MetacriticGateway.fetch_review_page(route, cursor)` | allowlisted confirmed game/platform, ровно одна audience и initial/returned cursor | ordered page records, stable reported total, validated next cursor или exhausted; никакого перевода; arbitrary next URL запрещён |
| `ProcessingService.run(slot, clock)` | idempotent UTC trigger | persisted run result/counters; duplicate/overlap являются явным outcome |
| `CorpusBuilder.build(game, audience)` | persisted valid observations + policy version | immutable corpus и exact fingerprint; без сети/model |
| `SummaryProvider.generate(request)` | `{game_key,audience,reviews:[{id,text}]}` + versioned contour | provider response DTO/typed safe error; fake имеет тот же contract |
| `EnrichmentWorker.process_next(clock)` | next leased review или summary job | persisted outcome; core state не меняется |
| `CatalogQuery.list(filters)` | title substring, optional platform, rating order | deterministic page; Metascore max по `ASM-15`, null last |
| `CatalogQuery.detail(game_id)` | internal game ID | game/platforms/current summaries/staleness/similar games либо not found |
| `SimilarityService.rank(game_id)` | current saved catalog | до пяти versioned deterministic results с score components |

## Similarity policy `genre-jaccard` 1.0.0

[ADR-0002](decisions/0002-genre-similarity-policy.md) выбирает простой genre Jaccard
по результатам [замороженного comparison](../evals/similarity/comparison_report.json).
Исходный candidate `0.1.0` (`0.60 × genre_jaccard + 0.25 × platform_jaccard +
0.15 × same_developer`, eligibility по genre либо developer, cutoff `>= 0.15`)
сохранён в eval, но отвергнут: четыре случая нарушают `INV-NONMATCH`.

Production policy использует только пересечение непустых сохранённых жанров:
`score = |genres(query) ∩ genres(candidate)| / |genres(query) ∪ genres(candidate)|`.
Жанры сравниваются как множества целых labels после collapse whitespace/casefold;
пустые labels исключаются, synonyms/перевод/parent genres не выводятся.
Сортировка — score descending, title casefold, internal ID. Возвращается максимум
пять уникальных сохранённых IDs без self-match; отсутствие query или общих жанров
даёт пустой результат. Result содержит score, shared genres, policy ID/version.
Ranker принимает immutable snapshot, не читает ORM и не делает HTTP/model calls.
`catalog.queries.list_similar_games()` читает один SELECT snapshot IDs/title/genres
без platform join, передаёт tuple в ranker и берёт названия из того же snapshot.
Malformed stored JSON считается неизвестными жанрами. Карточка показывает shared
genres и ссылки через `game-detail` по saved ID; `q`/`platform` сохраняются через
переход и Back to results. Пустой результат отображается явно. Integration,
browser и public evidence принадлежат [SIM-VER-01](requirements/sim_ver_01_review.md).

Источник признака — JSON-LD `VideoGame.genre`: строка или массив строк, максимум
255 символов на исходный label, без NUL; неверные типы отклоняются до записи.
`GameDTO.genres` передаёт tuple либо `None`. Ingestion сохраняет canonical labels
в JSON-массиве `Game.genres`, удаляя дубли с сохранением исходного порядка.
Пустое/отсутствующее значение не затирает прежние жанры; новый непустой набор
заменяет их и устанавливает `genres_last_changed_fetch`. При сохранении старого
значения сохраняется и его отдельная provenance. Migration `catalog.0006`
добавляет поля без реконструкции истории: прежние записи получают `[]`/null до
обычного успешного detail ingest. Parser contract — `1.1.0`.

## Транзакционные инварианты

1. Source identity проверяется до изменения catalog; title/slug никогда не merge key.
2. Cursor двигается только вместе с checkpoint успешно разобранного segment.
3. Core success атомарен и независим от review/AI; partial enrichment не меняет `processed` candidate.
4. Failed/empty/valid source outcomes различаются; failed fetch не затирает прошлые данные.
   Core DTO проверяется до upsert: типы/размеры строк, platform identity duplicates,
   Metascore int 0–100 и finite Userscore 0–10 с одной значимой десятичной цифрой.
   Invalid main DTO сохраняет диагностируемую ошибку одной игры, остальные кандидаты
   партии продолжаются; invalid secondary Userscore сохраняет прежнее значение.
   Неожиданное исключение завершает текущий run/его попытки до выхода наружу.
5. Review content versions, page observations и corpus immutable; complete coverage и exact model input восстанавливаются без provider logs.
6. Одна audience на corpus/job/attempt/summary; critic и user не могут иметь общую попытку.
7. Одинаковые input + contour дают cache hit; изменение выбранного input или версии контура создаёт новую работу, изменение только несэмплированных reviews обновляет coverage/source fingerprint без траты AI quota.
8. Stale lease/fencing token не может подтвердить core/job success; terminal attempt не переоткрывается и не переписывается.
9. Summary claims коммитятся только после schema, support, audience и length validation.
10. Публичные queries не изменяют processing state и не получают secrets.

## Проверочная трассировка

| Требование / риск | Design oracle | Будущий evidence |
|---|---|---|
| `DATA-01–DATA-03`, `R-ID-01`, `R-DAT-01` | Unique source IDs, aliases, platform rows, provenance, non-destructive transaction | `IMP-02`, `HRD-01–HRD-03` integration/failure tests |
| `RUN-01`, `SEL-01–SEL-03`, `R-TIM-01–R-TIM-02` | Unique UTC slot, cycle/candidate state, lease/fencing, checkpoint | `IMP-03`, `HRD-02–HRD-03`, `PUB-02` |
| `AI-01–AI-03`, `R-AI-01–R-AI-02` | Complete paginated source snapshots, persisted original-language reviews, immutable token-bounded corpus, versioned attempts/model/time/usage, grounded claims, cache | Independent pagination fixture; multilingual token-boundary report; `REV-EVAL-01` frozen selection oracle; `IMP-04`, `HRD-04`, frozen summary eval |
| `UI-01–UI-05`, `R-UI-01` | Read-only deterministic list/detail queries and visible summary provenance/staleness | `IMP-05`, `IMP-07`, `PUB-03` |
| `SIM-01–SIM-03`, `R-SIM-01` | Genre Jaccard 1.0.0, hard exclusions, deterministic tie-break | `SIM-EVAL-01` frozen oracle; [IMP-06 comparison](../evals/similarity/comparison_report.json); `SIM-VER-01` integration evidence |
| `NFR-01–NFR-05`, `R-OPS-01` | Persistent state, isolated failure, unique work, run/job timestamps and counters | `HRD-02–HRD-05`, `PUB-02` |
| `NFR-06`, `R-TST-01`, `R-SEC-01`, `R-REP-01` | External protocols replaceable by fakes; no live calls/secrets/raw envelopes in CI | `IMP-01`, `HRD-06`, `REL-01–REL-03` |

## Явно не добавлено

- Нет Redis/Celery: две небольшие очереди являются domain rows PostgreSQL и используют один worker.
- Нет отдельного API/SPA: текущий публичный UI server-rendered.
- Нет Elasticsearch/vector DB/embeddings: поиск и similarity покрываются PostgreSQL/Django и простой policy.
- Нет event bus, distributed tracing backend или metrics cluster: persistent run/job records и bounded logs закрывают Must observability.
- Нет хранения полных HTML/provider responses/raw reasoning: для воспроизводимости достаточно hashes, typed extracted data, immutable input corpus и canonical output.
- Нет перевода и language-detection service: review text сохраняется и передаётся модели на исходном языке.

Любой из этих компонентов может появиться только после измеренного нарушения текущего контракта и нового решения, а не «на будущее».
