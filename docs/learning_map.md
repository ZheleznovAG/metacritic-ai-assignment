# Карта изучения проекта

Это не документация для ревьюера — это маршрут для вас самих, чтобы разобраться, как сервис
устроен и почему сделан именно так. Ссылки на код и документы — repo-relative (открываются
и в редакторе, и на GitHub). Внешние термины — на Wikipedia/официальные доки, без пересказа
своими словами там, где оригинал лучше.

Личный совет: не читайте всё подряд за один присест. Разделы 1–3 дают общую картину (час
чтения). Остальное — открывайте по мере интереса к конкретной части.

## 0. Что это вообще такое

Сервис раз в час обходит Metacritic, находит новые/оценённые игры, собирает отзывы критиков и
игроков, делает по ним ИИ-резюме (Groq, бесплатный тариф), считает похожие игры и отдаёт всё это
как веб-сайт. Изначально — тестовое задание, сейчас — ваш личный сервис, который вы продолжаете
дорабатывать.

## 1. С чего читать документы репозитория (порядок важен)

Правила такого порядка описаны в [`AGENTS.md`](../AGENTS.md#project-structure--sources-of-truth) —
он же объясняет, какой документ за что отвечает. Коротко:

1. [`assignment.md`](../assignment.md) — исходное задание, что вообще просили сделать.
2. [`methodology.md`](../methodology.md) — как велась разработка (циклы, доказательства, гейты).
3. [`docs/design.md`](design.md) — **главный технический документ**: как всё устроено сейчас.
   Читайте по разделам, не всё сразу — см. карту ниже.
4. [`docs/decisions/`](decisions/) — ADR, архитектурные решения с обоснованием и альтернативами,
   которые отклонили.
5. [`docs/risks.md`](risks.md) — реестр рисков и как их закрывали.
6. [`action_plan.md`](../action_plan.md) — журнал: что сделано, когда, каким коммитом, как
   проверено. Это то, что мы с вами вели весь этот разговор — каждое ваше решение там записано
   отдельной строкой с обоснованием.

Термины из мира разработки, если незнакомы:
[ADR (Architecture Decision Record)](https://en.wikipedia.org/wiki/Architectural_decision) —
короткий документ «выбрали X, а не Y, потому что...», фиксируется один раз и не переписывается
задним числом.

## 2. Общая схема потока данных

```
Metacritic (сайт)
      │
      ▼
[планировщик, раз в час] ──находит──▶ [игры] ──качает карточку──▶ [каталог: catalog.Game]
      │                                                                    │
      ▼                                                            ▼
[отбор кандидатов]                                          [сбор отзывов, worker]
                                                                    │
                                                                    ▼
                                                        [отбор ≤10 отзывов для ИИ]
                                                                    │
                                                                    ▼
                                                        [резюме через Groq] ──▶ [карточка на сайте]
                                                                    │
                                                                    ▼
                                                        [похожие игры, embeddings]
```

Каждая стрелка — отдельный раздел ниже, с кодом и тестами.

## 3. Ключевые термины (по одному предложению + ссылка)

Общие концепции разработки:
- **ORM** (Object-Relational Mapping) — код обращается к строкам БД как к объектам Python, а не
  пишет SQL руками: [Django ORM overview](https://docs.djangoproject.com/en/5.2/topics/db/queries/).
- **Миграция БД** — версионированное изменение схемы таблиц, применяется по порядку и без
  ручного SQL: [Django migrations](https://docs.djangoproject.com/en/5.2/topics/migrations/).
- **Идемпотентность** — повторный вызов той же операции не меняет результат второй раз:
  [Wikipedia: Idempotence](https://en.wikipedia.org/wiki/Idempotence).
- **`SELECT ... FOR UPDATE`** — блокировка строки в PostgreSQL, чтобы два процесса не
  обработали её одновременно: [PostgreSQL: explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html).
- **Fencing token** — растущий номер, который доказывает, что именно этот процесс всё ещё
  владеет задачей (а не просто «показалось»): [Martin Kleppmann: How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
  (раздел про fencing tokens).
- **Экспоненциальный backoff** — при повторной ошибке ждать всё дольше перед следующей попыткой:
  [Wikipedia: Exponential backoff](https://en.wikipedia.org/wiki/Exponential_backoff).
- **Docker Compose** — описание нескольких контейнеров (веб, БД, воркер) одним файлом:
  [Compose overview](https://docs.docker.com/compose/).

Специфика источника данных:
- **JSON-LD** — структурированные данные, встроенные в HTML-страницу (у Metacritic — название,
  жанр, дата выхода игры): [json-ld.org](https://json-ld.org/).
- **Nuxt / SSR hydration payload** — Metacritic собран на фреймворке Nuxt (Vue.js), который
  встраивает в HTML JSON-слепок серверных данных (`__NUXT_DATA__`), наш парсер читает его
  напрямую: [Nuxt: Data fetching](https://nuxt.com/docs/getting-started/data-fetching).

ИИ и текст:
- **Эмбеддинг (embedding)** — текст превращается в числовой вектор так, что близкие по смыслу
  тексты дают близкие векторы: [Wikipedia: Word embedding](https://en.wikipedia.org/wiki/Word_embedding).
- **Косинусное сходство** — как измеряется «похожесть» двух векторов:
  [Wikipedia: Cosine similarity](https://en.wikipedia.org/wiki/Cosine_similarity).
- **TF-IDF** — классический (не нейросетевой) способ сравнить тексты по совпадению ключевых слов:
  [Wikipedia: tf–idf](https://en.wikipedia.org/wiki/Tf%E2%80%93idf).
- **Z-score (стандартизация)** — приводит две разные шкалы оценок к одной, чтобы их можно было
  честно сложить: [Wikipedia: Standard score](https://en.wikipedia.org/wiki/Standard_score).
- **ONNX** — формат, в котором модель эмбеддингов реально исполняется у нас (без Python-фреймворка
  вроде PyTorch): [onnx.ai](https://onnx.ai/).
- **sentence-transformers / `all-MiniLM-L6-v2`** — конкретная модель, которую мы используем:
  [sbert.net](https://www.sbert.net/) — там же объяснение, зачем вообще нужны sentence embeddings.
- **nDCG@5** — метрика качества ранжирования: насколько хорошие результаты оказались в топ-5 и в
  правильном порядке: [Wikipedia: Discounted cumulative gain](https://en.wikipedia.org/wiki/Discounted_cumulative_gain#Normalized_DCG).

Деплой:
- **ACME / Let's Encrypt** — протокол автоматического получения TLS-сертификата:
  [Let's Encrypt: How it works](https://letsencrypt.org/how-it-works/).
- **Reverse-DNS (PTR-запись)** — обратное сопоставление IP → имя, в отличие от обычной
  (forward) A-записи имя → IP; это разница, которая нам сломала первый заход на HTTPS:
  [Wikipedia: Reverse DNS lookup](https://en.wikipedia.org/wiki/Reverse_DNS_lookup).

## 4. Модель данных: где что хранится

Читайте [`docs/design.md`, раздел «Логическая модель PostgreSQL»](design.md#логическая-модель-postgresql)
целиком один раз — это самый плотный, но самый полезный кусок документации. Он разбит на:
- [Каталог и provenance](design.md#каталог-и-provenance) — таблицы игр, платформ, источник каждого
  изменённого поля.
- [Почасовая обработка](design.md#почасовая-обработка) — как формируется дневной список кандидатов.
- [Скачанные отзывы и точный AI input](design.md#скачанные-отзывы-и-точный-ai-input) — как отзывы
  превращаются в ограниченную выборку для модели.
- [AI jobs, attempts и summaries](design.md#ai-jobs-attempts-и-summaries) — очередь задач на
  резюме и история попыток.

Код моделей (то же самое, но как реальные Django-классы с полями):
[`app/catalog/models.py`](../app/catalog/models.py),
[`app/processing/models.py`](../app/processing/models.py),
[`app/reviews/models.py`](../app/reviews/models.py),
[`app/summaries/models.py`](../app/summaries/models.py).

## 5. Почасовое обнаружение и планировщик

**Что делает:** раз в час проверяет, не пора ли обработать новый календарный день, находит до
20 новых игр (сначала «New Releases», потом постраничный «SEE ALL»), сохраняет их как кандидатов
на день.

- Код: [`app/processing/scheduler.py`](../app/processing/scheduler.py) (внешняя команда,
  проверка часового слота) → [`app/processing/selector.py`](../app/processing/selector.py)
  (сама логика отбора и обнаружения).
- Блокировки и владение задачей между процессами:
  [`app/processing/lease.py`](../app/processing/lease.py).
- Восстановление после падения/рестарта: [`app/processing/runner.py`](../app/processing/runner.py).
- Ручной запуск оператором (кнопка в `/ops/`, не по расписанию):
  [`app/processing/admission.py`](../app/processing/admission.py),
  [`app/processing/dispatcher.py`](../app/processing/dispatcher.py).
- Тесты, которые лучше всего объясняют поведение примерами:
  [`app/tests/test_processing_selector.py`](../app/tests/test_processing_selector.py) — каждый
  `test_ps0N_...` — это один описанный сценарий из мира «а что если...».

**Живой пример разбора конкретного бага** — как список игр и карточка игры разошлись
в данных самого источника, и почему это лечится списком исключений, а не правкой ID:
[`action_plan.md`, запись «Эксплуатационная находка, 2026-09-25»](../action_plan.md).
Код фикса: `EXCLUDED_LOCATORS` в [`selector.py`](../app/processing/selector.py).

## 6. Разбор страницы Metacritic (парсер)

**Что делает:** превращает HTML страницы в структурированные данные (`GameDTO`,
`ReviewPageDTO`) — читает JSON-LD и Nuxt-слепок, а не парсит вёрстку руками, где это возможно.

- Код: [`app/metacritic/parser.py`](../app/metacritic/parser.py).
- HTTP-адаптер (лимиты по времени/размеру ответа, повторные попытки при сетевой ошибке):
  [`app/metacritic/gateway.py`](../app/metacritic/gateway.py).
- Границы допустимых данных (что считается некорректным и отклоняется):
  [`app/metacritic/validation.py`](../app/metacritic/validation.py).
- Реальные сохранённые страницы для тестов (не выдуманные, настоящие HTML-снимки):
  [`app/tests/fixtures/metacritic/`](../app/tests/fixtures/metacritic/).
- Тесты парсера: [`app/tests/test_metacritic_parser.py`](../app/tests/test_metacritic_parser.py).

## 7. Сохранение игры (identity resolution)

Самая тонкая часть системы: как решить, что «эта игра» — та же самая, что мы уже видели, а не
дубликат и не подмена. Здесь же корень бага с Xevious.

- Код: [`app/catalog/ingest.py`](../app/catalog/ingest.py) — читайте `_resolve_game` и
  `apply_game_dto`. Комментарии в коде объясняют, почему конфликт identity **никогда** не
  разрешается автоматическим слиянием.
- Неразрушающее объединение полей (новое пустое значение не затирает старое непустое) — там же,
  `_merge_field`.
- Тесты с говорящими именами: [`app/tests/test_catalog_ingest.py`](../app/tests/test_catalog_ingest.py).

## 8. Сбор отзывов

**Что делает:** постранично обходит критические и пользовательские отзывы игры, определяет,
когда обход «завершён» (устойчивый снимок), переживает рост числа отзывов во время самого обхода.

- Код: [`app/reviews/collector.py`](../app/reviews/collector.py) — читайте docstring модуля
  первым, там прямо описан весь конечный автомат состояний (`pending → complete/empty/unstable`).
- Построение «корпуса» игры из уже скачанных отзывов:
  [`app/reviews/corpus.py`](../app/reviews/corpus.py).
- Иммутабельные версии текста отзыва при редактировании источником:
  [`app/reviews/versioning.py`](../app/reviews/versioning.py).
- Тесты: [`app/tests/test_reviews_collector.py`](../app/tests/test_reviews_collector.py) —
  особенно `UnstableRouteTests`/тесты про перезапуск generation.

## 9. Отбор отзывов для ИИ и сами резюме

**Что делает:** из всех собранных отзывов детерминированно выбирает ≤10 для модели (не просто
первые/случайные), режет длинные тексты по границе токена, а не по символам, резервирует место
под отрицательные отзывы, чтобы «Не понравилось» не оставалось пустым.

- Отбор: [`app/reviews/selection.py`](../app/reviews/selection.py).
- Эталон отбора (заморожен ДО того, как писался код-кандидат — это принцип, не формальность):
  [`evals/review_selection/metric.md`](../evals/review_selection/metric.md),
  расширение по тональности: [`evals/review_selection/sentiment_cases.json`](../evals/review_selection/sentiment_cases.json).
- Контракт запроса к модели (какая версия промпта, какая схема ответа, что считается
  «grounded», то есть подтверждённым реальными отзывами):
  [`app/summaries/contour.py`](../app/summaries/contour.py),
  промпт [`app/summaries/contour/`](../app/summaries/contour/).
- Сам вызов Groq и обработка ответа: [`app/summaries/groq_adapter.py`](../app/summaries/groq_adapter.py).
- Очередь задач, ретраи, бюджет токенов и квота (важно, если будете трогать что-то около ИИ):
  [`app/summaries/quota.py`](../app/summaries/quota.py),
  [`app/summaries/worker.py`](../app/summaries/worker.py).
- Оценка качества самих сгенерированных резюме (рубрика 0/1/2, не просто «похоже/непохоже»):
  [`evals/reviews/rubric.md`](../evals/reviews/rubric.md).

## 10. Похожие игры

**Что делает:** превращает текст игры в эмбеддинг, сравнивает эмбеддинги + TF-IDF, отсеивает
игры с заведомо чужим (перепутанным) описанием.

Три версии политики, каждая — со своим ADR и настоящими измерениями, читайте по порядку, чтобы
увидеть, как решение эволюционировало:
1. [ADR-0002](decisions/0002-genre-similarity-policy.md) — базовый метод по жанру (Jaccard),
   почему он был выбран первым.
2. [ADR-0003](decisions/0003-text-hybrid-similarity.md) — переход на текст/эмбеддинги, почему
   жанра оказалось недостаточно.
3. [ADR-0004](decisions/0004-foreign-description-gate.md) — как обнаружили, что четверть каталога
   несёт чужие описания, и что с этим сделали.

Код: [`app/similarity/text.py`](../app/similarity/text.py) (сама математика ранжирования, без
Django и без сети — читается отдельно от всего остального),
[`app/similarity/embedder.py`](../app/similarity/embedder.py) (обёртка над моделью),
[`app/catalog/similarity_index.py`](../app/catalog/similarity_index.py) (как worker в простое
считает эмбеддинги и пересобирает индекс, не блокируя веб).

Оценка методом (как измеряли, что лучше) — тоже эволюция в трёх слоях:
[`evals/similarity/metric.md`](../evals/similarity/metric.md) →
[`text_comparison.md`](../evals/similarity/text_comparison.md) →
[`text_comparison_v2.md`](../evals/similarity/text_comparison_v2.md).

## 11. Сайт (что видит посетитель)

- Список игр, поиск, фильтр, сортировка: [`app/presentation/views.py`](../app/presentation/views.py),
  [`app/catalog/queries.py`](../app/catalog/queries.py) (тут, например, логика «Metascore без
  оценки — в конец списка», см. `ASM-15` в [`docs/requirements/assumptions.md`](requirements/assumptions.md)).
- Как решается, что резюме показывать: свежее, «устаревшее» (`stale`) или «недостаточно данных»:
  [`app/presentation/summaries.py`](../app/presentation/summaries.py).
- Страница `/ops/` (мониторинг работы фоновых процессов, вход оператора):
  [`app/presentation/monitoring.py`](../app/presentation/monitoring.py),
  [`app/presentation/operators.py`](../app/presentation/operators.py).

## 12. Как всё это разворачивается

- Как собирается образ и что в нём лежит: [`Dockerfile`](../Dockerfile).
- Как поднимаются контейнеры локально/в проде: [`compose.yaml`](../compose.yaml),
  [`compose.production.yaml`](../compose.production.yaml).
- Пошаговая процедура переноса на новый сервер (то, чем мы с вами реально пользовались,
  разворачивая на <production-ip>): [`deploy/relocation_runbook.md`](../deploy/relocation_runbook.md).
- Полная процедура первого разворачивания и обновления: [`deploy/README.md`](../deploy/README.md).
- Как устроен HTTPS/Caddy и почему у нас была история с лимитом Let's Encrypt: тот же
  `deploy/README.md`, раздел «Enabling trusted TLS».

## 13. Как проверяется, что всё работает (тесты и оракулы)

Одно из самых необычных решений проекта: для «нечётких» задач (отбор отзывов, похожесть,
качество ИИ-резюме) сначала замораживается эталон и порог приёмки, и только потом пишется и
сравнивается код-кандидат — чтобы не подгонять решение под то, что получилось. Это явно
проговорено как правило в [`AGENTS.md`, раздел «Testing & Evidence»](../AGENTS.md#testing--evidence).

- Общий прогон всех проверок: [`scripts/check.py`](../scripts/check.py) — по сути, оглавление
  всех проверок проекта одной командой.
- `evals/` — весь блок замороженных эталонов, глоссарий терминов уже дан выше (nDCG, оракул =
  зафиксированный набор примеров + метрика + порог, до которого код не пишется).
- `app/tests/` — 475+ обычных тестов на реальном PostgreSQL 16, включая браузерный e2e-сценарий
  ([`app/tests/test_e2e.py`](../app/tests/test_e2e.py)) через настоящий Chromium.

## 14. Живая история решений (самое интересное для разбора)

Не документ, а хронология: [`action_plan.md`](../action_plan.md) — каждая строка это одно
решение с датой, обоснованием и ссылкой на проверку. Особенно поучительно перечитать подряд
записи «Улучшение сервиса» и «Эксплуатационная находка» — там видно живьём: как находили баг →
как проверяли гипотезу на реальных данных → почему выбрали именно такое решение, а не
«починить в лоб».

## Как двигаться дальше

Если хочется по-настоящему разобраться — берите один раздел выше, открывайте указанный код рядом
с соответствующим тестом и меняйте что-нибудь маленькое локально (`docs/relocation_runbook.md` —
если нужно поднять свою копию для экспериментов). Ломать локальную копию можно без всякого риска
для того, что развёрнуто сейчас.
