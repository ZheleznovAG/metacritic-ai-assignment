# Внутренние контракты и модель данных

- **Статус:** Accepted design baseline
- **Дата:** 2026-09-08
- **Задача:** `PLN-02`
- **Архитектура:** [`ADR-0001`](decisions/0001-minimal-stack-and-architecture.md)
- **Связи:** `RUN-01`, `SEL-01–SEL-03`, `DATA-01–DATA-03`, `AI-01–AI-03`, `UI-01–UI-05`, `SIM-01–SIM-03`, `NFR-01–NFR-06`

## Область решения

Документ задаёт тестируемые границы модулей, состояние PostgreSQL, транзакции и инварианты. Это логическая схема для будущих Django migrations, а не реализация.

Must-контур использует только уже выбранные Django, PostgreSQL и три application processes внутри Compose: `web`, `scheduler`, `worker`. `worker` последовательно выполняет два вида сохранённой enrichment-работы: получение отзывов и AI-суммаризацию. Redis, Celery, отдельный search/vector store, object storage, event bus и новый monitoring service не добавляются.

## Сквозной поток

```text
UTC hourly slot
  -> core selection and Game/GamePlatform commit
  -> ReviewCollectionJob
  -> platform-specific review pages
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
| `game` | `source`, `source_game_id`, current locator, title, cover URL, developer, description, video URL, ordered normalized genre names, `last_changed_fetch_id`, timestamps | `UNIQUE(source, source_game_id)`; обязательны identity/title/locator; source text хранится без перевода |
| `game_alias` | `game_id`, source locator, first/last seen UTC | `UNIQUE(source, locator)`; alias другого game вызывает conflict, не merge |
| `game_platform` | `game_id`, `source_platform_id`, `source_game_platform_id`, slug/name, Metascore, Userscore, critic/user route, `last_changed_fetch_id` | `UNIQUE(game_id, source_platform_id)` и `UNIQUE(source, source_game_platform_id)`; score ranges; `null` не равен нулю |
| `source_fetch` | owning run или review job, kind, URL, started/completed UTC, HTTP status, response SHA-256, parser contract version, outcome/error code | Ровно один owner; полный HTML, cookies и authorization headers не сохраняются; `succeeded/empty/failed` различаются явно |

`last_changed_fetch_id` указывает на fetch, из которого принято текущее значение. Failed/structurally invalid fetch создаёт evidence, но не меняет хорошее поле. Отсутствовавшая в partial response платформа не удаляется.

### Почасовая обработка

| Таблица | Ключевые данные | Обязательные ограничения |
|---|---|---|
| `processing_lease` | singleton resource `ingestion`, monotonic fencing token, owner run, expiry/heartbeat UTC | Один действующий owner; новый token делает старые commits недействительными |
| `daily_cycle` | business date/timezone, phase, browse page/offset checkpoint, exhausted flag | `UNIQUE(business_date, timezone)`; phase: `new_releases_pending/browse/exhausted` |
| `processing_run` | unique trigger key, scheduled slot UTC, business day snapshot, status, start/end, counters, error code | `UNIQUE(trigger_key)`; один scheduled key вида `scheduled:<UTC-hour>` не создаёт повторную работу |
| `daily_candidate` | cycle/game, immutable source order, state, next retry UTC, last error | `UNIQUE(cycle_id, game_id)` и `UNIQUE(cycle_id, source_order)`; `pending/processing/processed/retryable/failed` |
| `core_attempt` | candidate/run, attempt number, fencing token, start/end, outcome/error | `UNIQUE(candidate_id, attempt_no)`; success допустим только при текущем fencing token |

Scheduler проверяет текущий UTC slot не реже раза в минуту. Restart в том же часу переиспользует trigger key; прошедший час без run фиксируется как наблюдаемый gap, но не создаёт burst из старых batch. Global lease TTL — 45 минут с heartbeat; core candidate имеет не более пяти автоматических attempts и остаётся видимым/reopenable после `failed`.

Identity check, non-destructive Game/GamePlatform upsert, закрытие `core_attempt` и перевод candidate в `processed` выполняются одной транзакцией. Review/AI work создаётся после core success и не входит в лимит 20.

### Скачанные отзывы и точный AI input

| Таблица | Ключевые данные | Обязательные ограничения |
|---|---|---|
| `review_collection_job` | game, audience, originating candidate, state, attempt count, available/lease timestamps, last error | `UNIQUE(daily_candidate_id, audience)`; audience только `critic/user`; работа retryable независимо от core |
| `review` | game/platform/audience, source review ID если есть, deterministic identity key, author/source label, score/date labels, `text_original`, content SHA-256, `first_seen_at`, optional `supersedes_review_id` | Вся content version после insert неизменяема; `UNIQUE(game_platform_id, audience, identity_key, content_sha256)`; last seen выводится из observations |
| `review_observation` | successful `source_fetch_id`, `review_id`, source position | `UNIQUE(source_fetch_id, source_position)` и `UNIQUE(source_fetch_id, review_id)`; задаёт точный состав route response |
| `review_corpus` | game/audience, policy version, source-set fingerprint, model-input fingerprint, created UTC, route/review/character coverage counters | `UNIQUE(game_id, audience, policy_version, source_set_fingerprint)`; corpus после создания неизменяем |
| `review_corpus_item` | corpus, ordinal, prompt review ID, `review_id`, exact `input_text`, SHA-256, truncation flag | Отдельные `UNIQUE(corpus_id, ordinal)`, `UNIQUE(corpus_id, prompt_review_id)` и `UNIQUE(corpus_id, review_id)`; support может ссылаться только на item этого corpus |

`text_original` — весь plain text каждого реально полученного review card после единственной механической нормализации: HTML decode, trim и collapse whitespace. Язык, формулировка и смысл не меняются. Текст хранится даже если не попал в ограниченный model input. Полный HTML страницы не хранится; его SHA-256 и extraction metadata находятся в `source_fetch`.

Если Metacritic отдаёт стабильный review ID, `identity_key=id:<value>`. Иначе используется `fallback:<SHA-256>` от audience, platform ID, author/source label, published label, score и полного нормализованного текста. Изменение текста со стабильным ID создаёт новую immutable version и `superseded` link; без стабильного ID система не заявляет, что две разные версии — один логический отзыв.

Для каждого известного platform/audience route collection job получает одну подтверждённую review page и сохраняет все cards из ответа. Непроверенная pagination не обходится. Failed route не удаляет прошлые observations; corpus использует последние valid snapshots и фиксирует `fresh/stale/failed/expected` coverage. Восстановившийся route создаёт новый source-set fingerprint.

Corpus для одной игры и ровно одной аудитории строится детерминированно:

1. Берутся review records из последних valid snapshots всех известных platform routes этой аудитории.
2. Точные cross-platform повторы удаляются по canonical author/date/score/text fingerprint.
3. Records round-robin чередуются по стабильному `source_platform_id`, внутри route сохраняется source position.
4. В model input входит не более 10 reviews, не более 2,000 Unicode characters одного review и не более 12,000 characters суммарно. Полный сохранённый текст не обрезается; exact bounded slice записывается в `review_corpus_item.input_text` с `was_truncated`.
5. Prompt IDs назначаются после сортировки как `R01…R10`. `input_fingerprint` — SHA-256 canonical JSON из game identity, audience, policy version и ordered `{id,text}`. Изменение данных вне выбранного input меняет source-set fingerprint, но не расходует AI quota.

Если доступно меньше трёх записей, job завершается `insufficient_data` детерминированно без provider call. При трёх и более records окончательное решение о содержательности остаётся частью прошедшего prompt/schema contract: общие оценки без наблюдения могут дать `insufficient_data`.

### AI jobs, attempts и summaries

| Таблица | Ключевые данные | Обязательные ограничения |
|---|---|---|
| `summary_job` | game/audience, source corpus, input fingerprint, contour fingerprint, state, attempts, available/lease UTC, last safe error | `UNIQUE(game_id, audience, input_fingerprint, contour_fingerprint)`; неизменный input/config является cache hit |
| `summary_attempt` | job/attempt, provider/API, requested model, optional returned model/provider system fingerprint, prompt/schema/preparation/normalizer/adapter versions + hashes, allowlisted generation parameters, `started_at`/`completed_at` UTC, `latency_ms`, prompt/completion/total tokens, outcome/error | `UNIQUE(job_id, attempt_no)`; после terminal outcome неизменяема; secret, provider request ID, raw reasoning и raw response envelope не сохраняются |
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

Job states: `pending -> running -> succeeded | insufficient_data | retryable | delayed_capacity | failed`. Lease — 5 минут; один worker, `SELECT … FOR UPDATE SKIP LOCKED`, fencing token и heartbeat. Transport/timeout/5xx используют bounded backoff `1m, 5m, 15m, 1h, 6h`, максимум пять автоматических attempts. `429` использует provider reset time и `delayed_capacity`, не включает paid fallback. Malformed/unsupported output становится `retryable`, прошлый опубликованный summary не затирается.

Summary и claims сохраняются одной транзакцией только после normalizer и canonical validation. Card показывает последний валидный summary; если current input/config уже имеет pending/error job, старый результат помечается stale с причиной. Для прозрачности рядом доступны returned model ID, `generated_at` и число reviews exact corpus; исходные отзывы публично не выводятся как часть Must UI.

## Внутренние interfaces

| Interface | Вход | Результат / error contract |
|---|---|---|
| `Clock.now_utc()` | нет | aware UTC datetime; fake clock в тестах |
| `MetacriticGateway.list_new_releases()` | source contract version | ordered identity DTO + `SourceFetch`; typed unavailable/invalid/identity errors |
| `MetacriticGateway.iter_browse(cursor)` | page/offset cursor | ordered segment + next cursor/exhausted; cursor не меняется при failure |
| `MetacriticGateway.fetch_game(identity)` | confirmed game identity | typed game/platform DTO + provenance; mismatch запрещает save |
| `MetacriticGateway.fetch_reviews(platform, audience)` | confirmed platform и ровно одна audience | complete observed first-page records + fetch outcome; никакого перевода |
| `ProcessingService.run(slot, clock)` | idempotent UTC trigger | persisted run result/counters; duplicate/overlap являются явным outcome |
| `CorpusBuilder.build(game, audience)` | persisted valid observations + policy version | immutable corpus и exact fingerprint; без сети/model |
| `SummaryProvider.generate(request)` | `{game_key,audience,reviews:[{id,text}]}` + versioned contour | provider response DTO/typed safe error; fake имеет тот же contract |
| `EnrichmentWorker.process_next(clock)` | next leased review или summary job | persisted outcome; core state не меняется |
| `CatalogQuery.list(filters)` | title substring, optional platform, rating order | deterministic page; Metascore max по `ASM-15`, null last |
| `CatalogQuery.detail(game_id)` | internal game ID | game/platforms/current summaries/staleness/similar games либо not found |
| `SimilarityService.rank(game_id)` | current saved catalog | до пяти versioned deterministic results с score components |

## Similarity policy `1.0.0`

Baseline считается в Python по текущей базе, без сохранённого similarity index:

`score = 0.60 × genre_jaccard + 0.25 × platform_jaccard + 0.15 × same_developer`

Кандидат допустим, если это другая Game, есть хотя бы один общий genre либо тот же non-empty normalized developer, и `score >= 0.15`. Результаты сортируются по score descending, затем title casefold и internal ID; возвращаются первые пять уникальных Game. Пустые признаки дают вклад `0`, а не фиктивное совпадение. На карточке можно объяснить совпавшие genres/platforms/developer.

Политика использует только уже необходимые сохранённые признаки, не переводит description и не добавляет embeddings/vector service. `IMP-06` замораживает relevance golden set; непройденный threshold требует пересмотра policy version, а не скрытой подстройки теста.

## Транзакционные инварианты

1. Source identity проверяется до изменения catalog; title/slug никогда не merge key.
2. Cursor двигается только вместе с checkpoint успешно разобранного segment.
3. Core success атомарен и независим от review/AI; partial enrichment не меняет `processed` candidate.
4. Failed/empty/valid source outcomes различаются; failed fetch не затирает прошлые данные.
5. Review content versions, observations и corpus immutable; exact model input восстанавливается без provider logs.
6. Одна audience на corpus/job/attempt/summary; critic и user не могут иметь общую попытку.
7. Одинаковые input + contour дают cache hit; изменение reviews или версии контура создаёт новую работу.
8. Stale lease/fencing token не может подтвердить core/job success; terminal attempt не переоткрывается и не переписывается.
9. Summary claims коммитятся только после schema, support, audience и length validation.
10. Публичные queries не изменяют processing state и не получают secrets.

## Проверочная трассировка

| Требование / риск | Design oracle | Будущий evidence |
|---|---|---|
| `DATA-01–DATA-03`, `R-ID-01`, `R-DAT-01` | Unique source IDs, aliases, platform rows, provenance, non-destructive transaction | `IMP-02`, `HRD-01–HRD-03` integration/failure tests |
| `RUN-01`, `SEL-01–SEL-03`, `R-TIM-01–R-TIM-02` | Unique UTC slot, cycle/candidate state, lease/fencing, checkpoint | `IMP-03`, `HRD-02–HRD-03`, `PUB-02` |
| `AI-01–AI-03`, `R-AI-01–R-AI-02` | Persisted reviews, immutable corpus, versioned attempts/model/time/usage, grounded claims, cache | `IMP-04`, `HRD-04`, frozen eval |
| `UI-01–UI-05`, `R-UI-01` | Read-only deterministic list/detail queries and visible summary provenance/staleness | `IMP-05`, `IMP-07`, `PUB-03` |
| `SIM-01–SIM-03`, `R-SIM-01` | Versioned local scoring, hard exclusions, deterministic tie-break | `IMP-06` invariant tests + golden set |
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
