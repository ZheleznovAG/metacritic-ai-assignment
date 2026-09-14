# План действий: master tracker

- Baseline: **1.0**, задача `PLN-03`, 2026-09-09 (Asia/Novosibirsk).
- Bonus scope: `pending`.
- [Повторный аудит `6551e42`](docs/requirements/implementation_audit_6551e42.md) выявил 19 findings и подтвердил исправления R02/R15. После [R03–R06](docs/requirements/imp_04_snapshot_correction.md) и [серии оставшихся 15 corrections](docs/requirements/implementation_corrections_batch.md) открытых findings этого аудита нет. [24 исходных probes и observations](research/reviews/6551e42/README.md) сохраняются как историческое evidence.
- Разрешённая пользователем пачка завершена: 261 application tests и offline checks пройдены локально и в Linux/Docker; browser/CSS/mobile checks и screenshots сохранены. [Verification excerpts и source hashes](docs/evidence/audit-batch-verification.txt). Hosted/public evidence и gates этой серией не закрываются; application DB не мигрировалась.

## Источники истины и правила

[assignment.md](assignment.md) задаёт scope; [methodology.md](methodology.md) — процесс; [implementation_plan.md](implementation_plan.md) — результаты, декомпозицию, оценки и Requirement/Risk mappings. [ADR](docs/decisions/0001-minimal-stack-and-architecture.md), [design](docs/design.md), [acceptance](docs/requirements/acceptance.md), [assumptions](docs/requirements/assumptions.md) и [risks](docs/risks.md) сохраняют свои роли.

Этот файл — единственное место текущих task/gate статусов, зависимостей и ссылок на фактическое evidence. Описания задач и численные оценки не копируются сюда. Исторические review фиксируют состояние на дату проверки, а не конкурирующие текущие статусы.

1. Один цикл: одна задача → author → adversarial review → verify → один focused commit → стоп. Новая задача начинается следующим циклом. При внешнем blocker текущий цикл можно приостановить и взять одну независимую Ready-задачу отдельным циклом; незавершённая задача сохраняет Blocked.
2. Все зависимости и предыдущие ворота должны быть выполнены. Проверенный code/документ без evidence не получает Verified; material finding даёт Changes requested.
3. При human input: Blocked / Ask, один конкретный вопрос и needed-by gate; до ответа доступны только независимые задачи. Уже полученные решения действуют.
4. Пригодность метода не принимается до замороженного oracle; live source/provider checks отделены от deterministic CI.
5. Таблица задаёт **конъюнкцию** зависимостей. Колонка «Ветка»: base — всегда, bonus1/bonus2 — только после выбора в BON-00. Суффикс `?` означает зависимость GB только при активной ветке; после отказа невыбранные task rows получают Dropped с основанием.
6. При Verified ожидаемое evidence заменяется ссылкой на существующий артефакт/check. Плановые ссылки/имена не являются доказательством.
7. Для hosted CI разрешён candidate-коммит незавершённой задачи с её фактическим статусом. После разрешённого push записываются run URL и проверенный SHA; evidence/status оформляются отдельным focused-коммитом. CI проверяет и этот коммит. Candidate-коммит не закрывает задачу. Локальная проверенная correction может быть закоммичена отдельно при сохранении внешнего blocker.
8. Поле Bonus scope выше — единственный текущий выбор: pending до принятия BON-00, затем none/bonus1/bonus2/both со ссылкой на решение в evidence BON-00. Невыбранные ветви получают Dropped; обязательные задачи исключать нельзя.

Статусы: Planned — описано; Ready — можно брать; In progress — выполняется; Changes requested — требуется исправление; Verified — критерий доказан; Blocked — внешний вход отсутствует; Dropped — исключён только необязательный scope с основанием.

## Приоритет текущего цикла

[Очередь исправлений](docs/requirements/implementation_audit_6551e42.md#очередь-исправлений) закрыта локальными и Docker regressions. [Повторная проверка IMP-02](docs/requirements/imp_02_revalidation.md) завершена: Elden Ring прошла source → VDS DB → публичную карточку; retained-score provenance исправлен, 263 tests прошли локально/в hosted CI, corrected source `92c846a` развёрнут и повторно проверен. [SIM-EVAL-01](docs/requirements/sim_eval_01_review.md) закрыт: владелец принял frozen oracle 1.0.0 2026-09-14 без изменений; IMP-06 разблокирован. [Повторная проверка IMP-03](docs/requirements/imp_03_revalidation.md) завершена: реальный scheduler нашёл и закрыл живой баг (userscore-виджет искался по всей странице вместо своего контейнера, что либо падало на "null", либо подставляло чужую оценку из карточки отзыва); фикс подтверждён настоящим автоматическим тиком на границе часа. [Повторная проверка IMP-04](docs/requirements/imp_04_revalidation.md) завершена: реальный worker нашёл и закрыл живой баг (score-only отзыв с `quote:null`), затем один реальный Groq call (в рамках free tier) подтвердил весь AI/collection/queue контур end-to-end. [Повторная проверка IMP-05](docs/requirements/imp_05_revalidation.md) завершена: исправлен overflow длинного названия, 35 fixture/browser checks и 50 public checks пройдены; CI и VDS upgrade source 5a038d4 подтверждены. [IMP-06](docs/requirements/imp_06_review.md) завершён: genre Jaccard 1.0.0 прошёл frozen comparison; genre storage/provenance, 284 tests и hosted CI для source `813c5d0` подтверждены. Следующий цикл — SIM-VER-01. G4–G7 не закрыты. Локальная application DB не мигрировалась; до её запуска нужны [миграции](README.md), затем обычный успешный collection/build для verified current heads; исторические incomplete данные не реконструируются.

## Исторические циклы до аудита 2026-09-12

`IMP-01` закрыт независимым adversarial review в отдельной сессии ([imp_01_independent_review.md](docs/requirements/imp_01_independent_review.md)): все заявленные exit criteria (build/tests/security posture, hosted CI run [34574112620](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34574112620), VDS redeploy) воспроизведены заново в этой сессии с идентичным результатом; найдена и исправлена одна тривиальная документационная неточность (устаревшая строка в README.md).

`IMP-02` закрыт ([imp_02_review.md](docs/requirements/imp_02_review.md)): реальный multiplatform game (Elden Ring) прошёл end-to-end от живого источника через непрозрачный `(source, source_game_id)` upsert до публичной read-only карточки; sanitised HTML/SSR fixtures и независимые expected values построены до parser; non-destructive merge, естественный `null` (Xbox One/PlayStation 4 Metascore) и атомарность core/job intent (forced rollback test) проверены; пять последовательных живых запуска против реального сайта подтвердили idempotency без дублей. Три раунда adversarial review — собственный `/code-review high` и два прохода независимой проверки кода отдельной параллельной сессией (`metacritic-ai-assignment-dc`), не запрошенной этой сессией, включая повторную проверку уже применённого исправления — нашли и закрыли семь реальных дефектов (несинхронизированный `source_game_platform_id`, `javascript:`-URL без проверки схемы, отсутствие проверки canonical/og:url против misrouted fetch, выбор первой попавшейся `game-title` записи вместо совпадающей по slug, потерянная provenance для fanned-out platform fetches, blank-string не защищённый non-destructive merge, provenance-указатель на неудавшийся fetch при сохранённом старом значении — закрыт разделением `last_changed_fetch` на отдельные Metascore/Userscore поля) до коммита; один known limitation (деградация extraction неотличима от естественного отсутствия) задокументирован для `HRD-01`. `IMP-03` теперь `Ready`; независимые циклы `REV-EVAL-01`/`SIM-EVAL-01` остаются доступны параллельно.

`IMP-03` закрыт ([imp_03_review.md](docs/requirements/imp_03_review.md)): полная модель состояний `SPK-04` (`ProcessingLease`/`ProcessingRun`/`CoreAttempt`, реальный `DailyCycle`/`DailyCandidate` state machine) реализована; Selector детерминированно покрывает 11 из 12 paper scenarios `SPK-04` (`PS-11` — AI failure — структурно тривиален до `IMP-04`; `PS-12` — non-UTC timezone — не реализован, UTC default `ASM-01` эксплицитно достаточен). Реальный scheduler (`scripts/run_scheduler.py`, отдельная `SCHEDULER_DB_USER` роль) трижды подряд сработал точно на реальной часовой границе без вмешательства (12:00, 13:00 и 14:00 UTC), real retry двух подлинных transient-сбоев сети (не смоделированных) и real same-hour idempotency (skipped_duplicate без лишних HTTP). Живая проверка нашла и закрыла один реальный баг парсера, обнаруженный собственным вторым запуском scheduler'а: canonical-проверка SEE ALL страниц ошибочно требовала точное совпадение `?page=N`, хотя реальный источник canonicalизирует все страницы листинга к одному base URL независимо от номера страницы (подтверждено на трёх реальных снимках: page 1/2/7429); фикс — path-only проверка только для browse-листинга, строгая проверка для game-detail/platform страниц не тронута; процесс перезапущен с фиксом после второго запуска, и уже третий запуск (14:00 UTC) прошёл с фиксом автоматически — `browse_page` успешно получена, курсор продвинулся, статус `succeeded` — так фикс подтверждён не только прямым live-вызовом парсера, но и реальным automated tick. Финальный adversarial self-review (отдельный fork-проход по всему diff) нашёл второй реальный баг до коммита: `Selector.run_batch` ошибочно классифицировал batch, где отказали вообще все элементы, как `partial` вместо `failed` (расходится с таблицей статусов `SPK-04`); исправлено, добавлен регрессионный тест. `IMP-04` остаётся `Planned` в ожидании `REV-EVAL-01`; независимые циклы `REV-EVAL-01`/`SIM-EVAL-01` остаются доступны параллельно.

`REV-EVAL-01` закрыт ([rev_eval_01_review.md](docs/requirements/rev_eval_01_review.md)): 8 синтетических full-corpus cases (`evals/review_selection/cases.json` `1.0.0`) покрывают все требуемые категории — multi-page/platform, first-page bias, last-page bias, sentiment skew, редкая тема, cross-platform дубли, длинный текст с token-boundary truncation, семиязычный multilingual mix, изменение отзыва вне sample. Метрика — 8 бинарных hard invariants (не rubric: partial credit не имеет смысла для structural correctness), заземлённых в уже принятых `ASM-16`/`ASM-17`/`ASM-19` и pagination-контракте `SPK-02`, плюс явный non-goals раздел (sentiment/rare-topic representativeness — observational, не gated, поскольку принятая `ASM-16` policy не content-aware). `baseline_naive.py` (простой baseline из формулировки задачи) корректно проваливает ровно 3 из 8 invariants (`INV-PAGE-COVERAGE` дважды, `INV-DEDUP` один раз) — commited evidence в `baseline_report.json`, доказывающая discriminative power oracle до появления реального `IMP-04` candidate. 9/9 meta-tests scorer'а (`test_score_selection.py`) подтверждают, что сам scorer ловит каждый класс дефектного selector'а. Финальный adversarial self-review (отдельный fork-проход) нашёл два overclaim в evidence-документе (заявленный "десятиязычный" mix на деле семиязычный; детерминизм/content-independence naive baseline описаны как "легко получить случайно", хотя они гарантированы конструкцией sort key, не читающего content) и один реальный пробел (`INV-CONTENT-INDEPENDENCE` был structural no-op для любого case с пулом ≤10 — нечего исключать) — все три исправлены (invariant теперь `n/a` при пуле ≤10 review, docs скорректированы) до Ask. Автор не видел и не писал `IMP-04` код до заморозки. Согласно правилу 3 методологии задан один конкретный `Blocked / Ask`; владелец принял oracle как frozen 2026-09-12 без изменений. `IMP-04` разблокирован по этой зависимости.

`IMP-04` закрыт ([imp_04_review.md](docs/requirements/imp_04_review.md)): полная схема `docs/design.md` для сбора отзывов, построения corpus и AI-резюме реализована (`catalog.SourceFetch` расширен review-page evidence; `reviews` app — реальный `ReviewCollectionJob` state machine, `Review`/`ReviewObservation`/`ReviewCorpus`/`ReviewCorpusItem`; новый `summaries` app — `SummaryJob`/`SummaryAttempt`/`ReviewSummary`/`SummaryClaim`). Реальный backend review-page gateway/parser против `backend.metacritic.com` с свежими sanitised fixtures (Bayonetta xbox-360, 6 файлов, независимо построенный oracle). `reviews/selection.py` реализует точную ASM-16 candidate `1.0.0` policy и проверен против принятого `REV-EVAL-01` oracle отдельным `verify_candidate.py` (не меняющим frozen файлы) — **8/8 invariants пройдено**, там где naive baseline проходил только 5/8; теперь входит в автоматический `scripts/check.py`. `tiktoken` стал core-зависимостью проекта в этом цикле. Row-leased durable collector (`reviews/collector.py`) и production Groq adapter/worker (`summaries/{contour,groq_adapter,quota,worker,observability}.py`) с реальной HTTP-механикой, персистентным quota admission (без отдельной таблицы-счётчика — ledger это закоммиченные `SummaryAttempt`), cache-hit по fingerprint, explicit delayed_capacity без paid fallback. Реальный live-прогон (`scripts/run_worker.py`, отдельная `WORKER_DB_USER` роль) против 182 реальных `ReviewCollectionJob` из более ранних живых прогонов IMP-02/03: 30/30 реальных review_page fetches успешны, 776 реальных отзывов собрано, 5 маршрутов достигли terminal state (включая настоящий valid zero-total `empty`); для игры Orbitals (1 платформа) оба audience corpus/summary job создались автоматически по завершении маршрута, и **два реальных вызова Groq вернули настоящие grounded резюме** (openai/gpt-oss-20b, 2175 и 1942 токена) — карточка `/games/14/` отрисовывает оба честно, без сырых отзывов. Между двумя реальными Groq-вызовами живьём воспроизведена настоящая quota-задержка (`delayed_capacity`, `quota_exhausted`, ноль потраченной квоты) и последующее автоматическое восстановление после реального истечения окна — тот же механизм, что и в fake-provider test suite (`test_summaries_worker.py`, 8 тестов на cold/unchanged/changed/quota/malformed/insufficient/lease-loss сценарии), теперь подтверждён реальным clock. Живая проверка нашла один реальный диагностический дефект: `last_error` не очищался при последующем успехе (`succeeded` рядом со старым `quota_exhausted`) — исправлено в `collector.py` и `worker.py`. Финальный adversarial self-review (отдельный fork-проход по всему diff) нашёл два реальных дефекта до коммита: (1) ни `reviews/collector.py`, ни `summaries/worker.py` не восстанавливали job, оставшийся в `running` после падения воркера — `lease_expires_at` записывался, но нигде не читался, и `claim_next_job` никогда не рассматривал `running` строки, то есть падение воркера навсегда блокировало эту работу; исправлено добавлением `_recover_stale_leases` в оба claim-пути (по аналогии с `processing.selector`'s stale-candidate recovery, адаптировано под per-row lease вместо одного singleton lease), с немедленным bump fencing token при обнаружении просроченной аренды; (2) `reviews/corpus.py::build()` содержал незащищённый check-then-create race (`filter().first()` без lock, затем `create()` без `get_or_create`) — под design.md's `SELECT ... FOR UPDATE SKIP LOCKED` моделью, рассчитанной на параллельных воркеров, два воркера могли одновременно пройти проверку и один падал с `IntegrityError`; исправлено try/except с возвратом выигравшей строки. Оба фикса подтверждены новыми регрессионными тестами, включая реальный two-thread `TransactionTestCase` для race-условия; полный suite (146 Django тестов) зелёный. `IMP-05` теперь разблокирован; независимый `SIM-EVAL-01` остаётся доступен параллельно.

`IMP-05` закрыт ([imp_05_review.md](docs/requirements/imp_05_review.md)): `catalog.queries.list_games()`/`list_platform_options()` реализуют точное правило `ASM-15` (без фильтра — максимум по всем платформам игры; с фильтром — максимум только среди совпавших платформ; без оценки — после оценённых; равенство — по названию), case-insensitive substring поиск и platform filter. `presentation.views.index`/`game_detail` — stateless, весь state в query string (`q`/`platform`), без server-side session; ссылка "← Back to results" на карточке — весь механизм для AC-UI-06 без нового persisted state. 20 новых тестов (33 unit + integration), включая точный round-trip test URL списка. Живой прогон против 41 реальной игры из IMP-02/03/04: поиск `?q=elden` вернул ровно 2 реальные записи Elden Ring, фильтр `?platform=pc` сузил список с 41 до 34, комбинация `?q=elden&platform=pc` показала реальный PC Metascore (94) вместо кросс-платформенного максимума (96) — конкретное подтверждение ASM-15's filtered-vs-unfiltered различия на живых данных. Три реальных скриншота (`docs/evidence/imp05-*.png`, one-off local `playwright`, не добавлен в pyproject.toml/uv.lock): список с реальными обложками, карточка Elden Ring с честным `pending` для обоих резюме (не все маршруты ещё terminal), карточка Orbitals с двумя реальными завершёнными Groq-резюме из IMP-04. UI-label language зафиксирован как English (уже де-факто конвенция, теперь explicit ASM-14 decision). Public VDS smoke и полный browser matrix явно отложены до PUB-03/ASM-25 по multi-gate trace table в docs/design.md — не единоличная обязанность IMP-05. Один механический fix: существующий IMP-01 тест `test_index_states_actual_scope` переведён с `SimpleTestCase` на `TestCase`, поскольку `/` теперь делает реальный DB query. Полный suite (166 Django тестов) зелёный. Независимый `SIM-EVAL-01` остаётся доступен; `IMP-06`/`SIM-VER-01`/`IMP-07` — следующие по цепочке зависимостей.

## Подготовка: G0–G2

| ID | Зависимости | Ветка | Статус | Evidence |
|---|---|---|---|---|
| [IN-01](intake.md) | — | base | Verified | [Intake](intake.md) |
| [G0](intake.md) | IN-01 | base | Verified | [Intake gate](intake.md) |
| [FOR-01](docs/requirements/context.md) | G0 | base | Verified | [Контекст](docs/requirements/context.md) |
| [FOR-02](docs/requirements/requirements.md) | FOR-01 | base | Verified | [Реестр](docs/requirements/requirements.md) |
| [FOR-03](docs/requirements/assumptions.md) | FOR-02 | base | Verified | [Допущения](docs/requirements/assumptions.md) |
| [FOR-04](docs/requirements/acceptance.md) | FOR-02, FOR-03 | base | Verified | [Приёмка](docs/requirements/acceptance.md) |
| [FOR-05](docs/requirements/g1_review.md) | FOR-04 | base | Verified | [Trace review](docs/requirements/g1_review.md) |
| [G1](docs/requirements/g1_review.md) | FOR-05 | base | Verified | [G1 review](docs/requirements/g1_review.md) |
| [RSK-01](docs/risks.md) | G1 | base | Verified | [Риски](docs/risks.md) |
| [SPK-01](research/feasibility/metacritic-access.md) | RSK-01 | base | Verified | [Доступ](research/feasibility/metacritic-access.md) |
| [SPK-02](research/feasibility/metacritic-contract.md) | SPK-01 | base | Verified | [Контракт источника](research/feasibility/metacritic-contract.md) |
| [SPK-03](research/feasibility/game-identity.md) | SPK-02 | base | Verified | [Identity](research/feasibility/game-identity.md) |
| [SPK-04](research/feasibility/processing-state.md) | RSK-01, FOR-03 | base | Verified | [Календарная модель](research/feasibility/processing-state.md) |
| [SPK-05](research/feasibility/ai-summary.md) | SPK-02 | base | Verified | [AI baseline](research/feasibility/ai-summary.md) |
| [SPK-06](research/feasibility/deployment.md) | RSK-01, FOR-01 | base | Verified | [VDS probe](research/feasibility/deployment.md) |
| [RSK-02](docs/requirements/g2_review.md) | SPK-03, SPK-04, SPK-05, SPK-06 | base | Verified | [Risk review](docs/requirements/g2_review.md) |
| [G2](docs/requirements/g2_review.md) | RSK-02 | base | Verified | [G2 review](docs/requirements/g2_review.md) |

## Implementation baseline: G3

| ID | Зависимости | Ветка | Статус | Evidence |
|---|---|---|---|---|
| [PLN-01](docs/decisions/0001-minimal-stack-and-architecture.md) | G2 | base | Verified | [ADR-0001](docs/decisions/0001-minimal-stack-and-architecture.md) |
| [PLN-02](docs/requirements/pln_02_review.md) | PLN-01 | base | Verified | [Исправленные контракты](docs/requirements/pln_02_review.md) |
| [PLN-03](docs/requirements/g3_review.md) | PLN-01, PLN-02 | base | Verified | [Baseline review](docs/requirements/g3_review.md) |
| `G3` | PLN-03 | base | Verified | [G3 review и offline checks](docs/requirements/g3_review.md) |

## Сквозная реализация: G4

| ID | Зависимости | Ветка | Статус | Evidence |
|---|---|---|---|---|
| [IMP-01](implementation_plan.md#imp-01) | G3 | base | Verified | [Revalidation 2026-09-14](docs/requirements/imp_01_revalidation.md): [hosted CI 34804143596](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34804143596), 261 application tests; source `8c76615` развёрнут на VDS, image identity, migrations, runtime permissions, external HTTP/CSS и ресурсы проверены. [Execution excerpts](docs/evidence/imp-01-revalidation-2026-09-14.txt). |
| [IMP-02](implementation_plan.md#imp-02) | IMP-01 | base | Verified | [Revalidation и provenance correction](docs/requirements/imp_02_revalidation.md): [CI 34808052113](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34808052113), 263 application tests; corrected source `92c846a` на VDS, 3 live ingest без дублей, все core fields/provenance, public card и desktop/mobile checks подтверждены. [Source/DB/public snapshots](docs/evidence/imp-02-revalidation-2026-09-14.json). |
| [IMP-03](implementation_plan.md#imp-03) | IMP-02 | base | Verified | [Revalidation 2026-09-14](docs/requirements/imp_03_revalidation.md): реальный scheduler нашёл и закрыл живой баг (`invalid_userscore` из-за несужен­ного поиска виджета на всей странице); фикс подтверждён реальным автоматическим тиком на границе часа (10:00 UTC, 20/20 processed); 265 local tests. |
| [REV-EVAL-01](implementation_plan.md#rev-eval-01) | G3, SPK-05 | base | Verified | [Oracle accepted 2026-09-12](docs/requirements/rev_eval_01_review.md): 8 cases, 8 hard invariants, naive-baseline evidence, owner Ask answered |
| [IMP-04](implementation_plan.md#imp-04) | IMP-03, REV-EVAL-01 | base | Verified | [Revalidation 2026-09-14](docs/requirements/imp_04_revalidation.md): реальный worker нашёл и закрыл живой баг (score-only отзыв с `quote:null` ошибочно считался невалидным); один реальный Groq call (grounded, 6 claims, в рамках free tier) подтвердил R01/R07/R09/R10/R13/R14/R18 end-to-end; 266 local tests. |
| [IMP-05](implementation_plan.md#imp-05) | IMP-04 | base | Verified | [Revalidation 2026-09-14 UTC](docs/requirements/imp_05_revalidation.md): overflow длинного названия исправлен; 35 fixture/browser checks, 50 public checks на 38 играх; [CI 34837423748](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34837423748) прошёл. Source `5a038d4` развёрнут на VDS, CSS/image identity и сохранность данных подтверждены; screenshots и execution evidence сохранены. |
| [SIM-EVAL-01](implementation_plan.md#sim-eval-01) | G3 | base | Verified | [Oracle 1.0.0 accepted 2026-09-14](docs/requirements/sim_eval_01_review.md): 14 synthetic cases, nDCG@5 mean ≥0.90 / each ≥0.80, 8 hard invariants; 14 meta-tests PASS; owner Ask answered — accepted as-is, no changes. Hosted CI initially failed on a missing `.dockerignore` allowlist entry; fixed and passed on [34828861545](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34828861545). |
| [IMP-06](implementation_plan.md#imp-06) | SIM-EVAL-01, IMP-02 | base | Verified | [Review и comparison](docs/requirements/imp_06_review.md): genre Jaccard 1.0.0 прошёл frozen oracle (mean/floor 1.0, все invariants); weighted candidate отвергнут. Genre DTO/storage/provenance и миграция проверены; 284 application tests PASS локально и в [hosted CI 34867974090](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34867974090), tested SHA `813c5d0afb68ae60d09afad660332d8bf4163057`; build, runtime и HTTP/CSS smoke PASS. |
| [SIM-VER-01](implementation_plan.md#sim-ver-01) | IMP-05, IMP-06 | base | Ready | Ожидается: Integration/E2E и relevance regression |
| [IMP-07](implementation_plan.md#imp-07) | IMP-03, SIM-VER-01 | base | Planned | Ожидается: Полный E2E и public smoke |
| `G4` | IMP-07 | base | Planned | Ожидается: IMP-07 report + все functional AC |

## Упрочнение: G5

| ID | Зависимости | Ветка | Статус | Evidence |
|---|---|---|---|---|
| [HRD-01](implementation_plan.md#hrd-01) | G4 | base | Planned | Ожидается: Parser/HTTP failure report |
| [HRD-02](implementation_plan.md#hrd-02) | G4 | base | Planned | Ожидается: Crash/restart/state report |
| [HRD-03](implementation_plan.md#hrd-03) | G4 | base | Planned | Ожидается: PostgreSQL concurrency report |
| [HRD-04](implementation_plan.md#hrd-04) | G4 | base | Planned | Ожидается: Final AI/failure/capacity eval |
| [HRD-05](implementation_plan.md#hrd-05) | G4 | base | Planned | Ожидается: Diagnostics/security/storage reports |
| [HRD-06](implementation_plan.md#hrd-06) | HRD-01, HRD-02, HRD-03, HRD-04, HRD-05 | base | Planned | Ожидается: Общий CI-run и G5 review |
| `G5` | HRD-06 | base | Planned | Ожидается: HRD-06 report + risk/quality review |

## Публичная валидация: G6

| ID | Зависимости | Ветка | Статус | Evidence |
|---|---|---|---|---|
| [PUB-01](implementation_plan.md#pub-01) | G5 | base | Planned | Ожидается: HTTPS URL, image/commit SHA и deploy log |
| [PUB-02](implementation_plan.md#pub-02) | PUB-01 | base | Planned | Ожидается: Два окна, reboot/restore, storage/AI measurements |
| [PUB-03](implementation_plan.md#pub-03) | PUB-02 | base | Planned | Ожидается: Внешний smoke и G6 review |
| `G6` | PUB-03 | base | Planned | Ожидается: PUB-02/PUB-03 evidence + public gate review |

## Условный Bonus: GB

| ID | Зависимости | Ветка | Статус | Evidence |
|---|---|---|---|---|
| [BON-00](implementation_plan.md#bon-00) | G6 | base | Planned | Ожидается: Scope ADR: none/bonus1/bonus2/both |
| [BON-11](implementation_plan.md#bon-11) | BON-00 | bonus1 | Planned | Ожидается: YouTube feasibility/disposition |
| [BON-12](implementation_plan.md#bon-12) | BON-11 | bonus1 | Planned | Ожидается: Video/eval/failure/public evidence |
| [BON-21](implementation_plan.md#bon-21) | BON-00 | bonus2 | Planned | Ожидается: Realtime UI/server consistency |
| [BON-22](implementation_plan.md#bon-22) | BON-21 | bonus2 | Planned | Ожидается: Auth/concurrency/shared-trigger evidence |
| `GB` | BON-00, BON-12?, BON-22? | base | Planned | Ожидается: Scope decision + evidence выбранных ветвей |

## Комплект и сдача: G7

| ID | Зависимости | Ветка | Статус | Evidence |
|---|---|---|---|---|
| [REL-02](implementation_plan.md#rel-02) | GB | base | Planned | Ожидается: README и docs/evidence.md |
| [REL-03](implementation_plan.md#rel-03) | GB | base | Planned | Ожидается: Archive manifest/privacy report |
| [REL-01](implementation_plan.md#rel-01) | REL-02, REL-03 | base | Planned | Ожидается: Release checklist, candidate SHA/digest |
| [REL-04](implementation_plan.md#rel-04) | REL-01 | base | Planned | Ожидается: Final links/version/archive check |
| [REL-05](implementation_plan.md#rel-05) | REL-04 | base | Planned | Ожидается: Отправленное сообщение и timestamp |
| `G7` | REL-05 | base | Planned | Ожидается: Release checklist + DEL-04 receipt |

## Условия ворот

Статус ворот находится только в таблицах выше. Выполнение зависимостей необходимо, но не заменяет содержательный gate review:

| Gate | Условие принятия |
|---|---|
| G0 | Исходник/обязательный и Bonus scope/комплект сдачи сохранены без подмены неизвестного |
| G1 | Все требования имеют ID, трактовку, критерий и ожидаемый evidence; неоднозначности видимы |
| G2 | Must-spikes имеют проверенный результат, решение и остаточный риск; Bonus изолирован |
| G3 | Полное Requirement/Risk покрытие; обоснованный стек; ацикличные зависимости; ранний public slice; fixtures/evals/failures/delivery и резерв учтены; статусы/описания не дублируются |
| G4 | Продуктовые функциональные Must RUN/SEL/DATA/AI/UI/SIM имеют первичное evidence, рабочий source→DB→UI путь, безопасное обновление, оба резюме/похожие игры, полный deterministic E2E и публичный срез |
| G5 | Отказные, календарные, recovery/concurrency, source validation и AI/similarity quality проверки проходят; diagnostics/security и полный suite подтверждены |
| G6 | Продуктовые и эксплуатационные Must подтверждены публично: реальные данные, HTTPS/external E2E, два последовательных application schedule windows, restart/redeploy/host-reboot persistence и isolated restore; capacity/storage ограничения измерены и не скрывают блокирующий Must-дефект |
| GB | BON-00 зафиксировал scope; выбранные ветки приняты с failure/eval/public evidence без Must-regression либо исключены; none закрывает gate записью решения |
| G7 | Все 28 Must, включая DEL-01–DEL-04, имеют evidence; candidate соответствует публичной версии; README/архив/ссылки проверены, секретов нет, ограничения открыты и отправка подтверждена |

`G6` не требует заранее выполнить отправку, архив и финальный repository/комплект check из `DEL-*`: эти delivery AC окончательно закрываются в `G7`. Это исправление зависимости ворот, не исключение требований. `G3` принимает план; оно не подтверждает production capacity, application tests или качество ещё не выбранных policies.

## Изменение baseline и сохранённая история

Baseline 1.0 (`PLN-03`) заменяет громоздкие task cards на master tracker и связанный implementation backlog, сохраняя все 46 Task IDs. Проверочные artifacts и git-история не удаляются. Предыдущий полный план и журнал 0.3–0.18 доступны через `git show 0c353ec:action_plan.md`; исходное задание имеет неизменный SHA-256 из intake.

Материальные изменения: IMP-04 зависит от готового календарного/ownership контура IMP-03; HRD-задачи явно стоят после G4; условные Bonus-ветки не блокируют none; REL-02/REL-03 готовят комплект до REL-01; G6/G7 разделяют public readiness и завершённую сдачу. Обоснование, проверка графа и явные ограничения бюджета — [g3_review.md](docs/requirements/g3_review.md).

Новый факт обновляет источник соответствующего решения/контракта, связанные задачи/риски и необходимые проверки. Нельзя задним числом ослаблять AC под реализацию или считать лимит timebox основанием для Verified.
