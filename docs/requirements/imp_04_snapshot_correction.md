# IMP-04: correction collection/snapshot/handoff — 2026-09-14

Scope: первый correction-цикл [аудита `6551e42`, R03–R06](implementation_audit_6551e42.md#очередь-исправлений),
`AI-01/02/03`, collection/input часть `AC-AI-03/05/06`, `NFR-01/02/04`,
`R-AI-01/02`, `R-DAT-01`, `R-TST-01`. Текущие task/gate статусы находятся только
в [action_plan.md](../../action_plan.md). Это локальное исправление существующего
IMP-04; hosted/public evidence и полное принятие AI-контракта требуют своих проверок.
Дата документа — Asia/Novosibirsk; прогоны завершены 2026-09-13 UTC.

## Поведение и контракт

[collector.py](../../app/reviews/collector.py) теперь считает unique reviews по
observations текущего job/generation. При повторном неизменном дне существующие
Review versions наблюдаются снова, collection завершается `complete`, а corpus
и summary job повторно используются. Счётчики не зависят от создания глобально
новой строки Review. Дубли и смена версии одного identity внутри обхода не могут
выдать успешный полный snapshot.

[versioning.py](../../app/reviews/versioning.py) определяет immutable version как
нормализованный текст вместе с author/score/date labels. `content_sha256` сохраняет
значение text-only hash; новый `version_sha256` позволяет сохранить изменение
только оценки, автора или даты отдельной версией. Старые observations и corpus
items продолжают ссылаться на прежние версии. Возврат текста A→B→A повторно
использует A; наличие исторической `superseded_by` больше не исключает её из
текущего snapshot.

[corpus.py](../../app/reviews/corpus.py) выбирает последний processed DailyCandidate
по business date/id и требует полного набора terminal routes именно этого дня.
Вход состоит только из observations соответствующих job/generation, подтверждённых
успешными SourceFetch. Missing/pending/running/retryable/unstable/failed route
блокирует новый corpus. Время завершения старого backlog не делает его текущим;
удалённые отзывы, неполный новый обход и предыдущие generations не примешиваются.

Source-set fingerprint версии 2 учитывает route identity/slug, terminal state,
counts и identity/version каждой наблюдаемой записи. Изменение metadata или
отзыва вне выбранных десяти меняет source fingerprint; изменение exact выбранного
текста меняет model-input fingerprint. Неизменные дни сохраняют оба fingerprint;
порядок страниц и DB/job IDs не делают новый AI input. Добавление пустой платформы
меняет coverage, сохраняя прежний exact input и summary job.

В ходе adversarial проверки обнаружена коллизия на границе builder/selector:
source ID ограничен платформой, а selector ожидает уникальный ключ в общем pool.
Для совпадающих ID разных платформ builder теперь передаёт квалифицированные
ключи. Разные тексты с одинаковыми source ID остаются отдельными отзывами;
настоящие author/date/score/text дубли по-прежнему объединяются. Сохранённый item
ссылается на версию выбранной платформы. Чистый selector, его policy version,
frozen examples, метрики и thresholds не изменялись. Обычные уникальные identity
сохраняют прежний hash input отбора.

Terminal page, observations/counters, corpus/items и summary job теперь входят
в одну транзакцию. Исключение после создания corpus, но до summary handoff,
откатывает всю terminal page. Lease reclaim возвращается к предыдущему cursor;
после успешного terminal commit summary intent уже сохранён. Порядок блокировок
Game → ReviewCollectionJob сериализует коммиты платформ одной игры; HTTP остаётся
за пределами транзакции. Отдельный builder тоже сохраняет corpus атомарно под
Game lock. Полный контракт находится в [design.md](../design.md#скачанные-отзывы-и-точный-ai-input).

## Миграция и существующие данные

[reviews.0004](../../app/reviews/migrations/0004_review_version_fingerprint.py)
добавляет nullable version hash, заполняет его пакетами по 1,000 записей, делает
поле обязательным и заменяет text-only unique constraint ограничением версии.
Формула хеша зафиксирована внутри миграции и не импортирует изменяемый runtime.
ID, text hash, текст, labels и ссылки history сохраняются.

Обновление существующей среды: остановить writers, применить обычный
`scripts/migrate.py` с migration-role, затем запустить обновлённый worker.
Команды окружения находятся в [README](../../README.md#local-development).
После появления нескольких metadata versions одного текста старая unique
constraint несовместима с данными: откат схемы не является безопасным способом
отката приложения. Нельзя удалять history ради успешного downgrade; перед
операционным upgrade нужен пригодный для восстановления backup.

Миграция не сбрасывает старые jobs и не реконструирует потерянные labels,
отброшенные observations или исторически неверные corpora. Она также не
переигрывает terminal jobs, у которых старый код уже потерял handoff. Следующий
обычный обработанный день использует исправленный collector; опубликованная
история сохраняется. Гарантия R06 распространяется на terminal commits новым
кодом. В этом цикле миграция выполнялась в отдельных тестовых БД; существующая
application DB и работающий production не обновлялись.

## Независимое executable evidence

Все проверки используют fake gateways/clocks и PostgreSQL 16; live Metacritic
и платные AI calls не выполнялись. Новые tests проверяют правильный исход через
реальные claim/collector/builder, а не подставляют готовый corpus.

| Exit criterion / контрпример | Проверка |
|---|---|
| R03: неизменный день, включая несколько страниц, завершён без новых versions/jobs | `test_unchanged_next_day_reuses_versions_corpus_and_summary_job`, `test_unchanged_next_day_counts_observations_across_multiple_pages` |
| R04: новый текст создаёт новый exact input; score/author/date сохраняются immutable | `test_one_edited_text_creates_new_input_without_mutating_old_corpus`, `test_metadata_only_edits_are_immutable_versions_and_reuse_exact_input` |
| R04: изменение вне sample и пустая новая платформа меняют coverage без лишнего AI job | `test_edit_outside_sample_changes_source_fingerprint_without_new_ai_job`, `test_new_empty_platform_changes_coverage_fingerprint_without_new_model_input` |
| R05: удаления, valid empty, partial и любой незавершённый current route | `test_deleted_reviews_and_valid_empty_route_do_not_reappear_from_history`, `test_partial_generation_never_contributes_to_a_completed_corpus`, `test_new_incomplete_route_blocks_old_terminal_fallback` |
| R05: смешение дней, поздний backlog, возврат A→B→A | `test_missing_current_platform_job_does_not_mix_daily_candidates`, `test_late_older_daily_job_cannot_replace_a_newer_snapshot`, `test_current_generation_can_reuse_a_previously_superseded_text_version` |
| Snapshot имеет подтверждённые observations; дубли/редактирование внутри обхода не создают corpus | `test_terminal_counts_require_observations_from_matching_successful_generation`, `test_duplicate_identity_is_not_a_second_review_even_if_unique_total_matches`, `test_identity_edited_mid_route_cannot_mix_versions_into_a_snapshot` |
| R06: сбой после corpus insert откатывает terminal page; reclaim завершает тот же cursor; после commit intent сохранён | `test_handoff_failure_rolls_back_terminal_page_and_reclaim_completes_it`, `test_crash_after_terminal_commit_already_has_durable_summary_job` |
| Аудитории разделены; одинаковые cross-platform records имеют корректную provenance | `test_same_source_ids_in_two_audiences_stay_separate`, `test_identical_cross_platform_reviews_deduplicate_with_correct_item_provenance` |
| Реальные два соединения: builders согласуются; две terminal платформы с пересекающимися IDs не теряют данные/handoff | `ConcurrentBuildRaceTests` |
| Заполненная старая схема: backfill 1,004 reviews, включая Unicode/null и границу batch; IDs/hash/FKs сохранены, metadata versions разрешены, повтор версии запрещён | `ReviewVersionMigrationTests` |

Первые восемь строк исполняются в
[test_reviews_snapshots.py](../../app/tests/test_reviews_snapshots.py) (19 tests),
конкурентность — в [test_reviews_corpus.py](../../app/tests/test_reviews_corpus.py)
(2 tests), upgrade — в [test_reviews_migrations.py](../../app/tests/test_reviews_migrations.py)
(1 test). Исходный concurrent-builder test обновлён: fixture теперь проходит
collector и создаёт реальные SourceFetch/observations.

До изменения реализации первые 13 snapshot regressions дали 17 failures, включая
subtests, на коде `11fc7a6` (application baseline `6551e42`). После исправления
все 22 целевые проверки прошли. Полный application suite вырос с 177 до 198 tests:
21 новая проверка и обновлённая существующая проверка race.
Исторические [24 defect probes](../../research/reviews/6551e42/README.md) сохранены
без изменения и не используются как acceptance gate исправления.

Воспроизводимые полные команды:

```powershell
.\.venv-app\Scripts\python.exe -B scripts/check.py
docker compose --env-file .env.app build web checks
docker compose --env-file .env.app run --rm checks
git diff --check
```

Локальный прогон Python 3.12 / PostgreSQL 16 завершился с exit 0: format/lint,
mypy (86 source files), Django checks, migration drift и static build прошли;
application `198 tests, OK`; scripts `6`, planning `18`, saved AI `7`, selection
`9` tests — OK. Frozen baseline сохранён без drift; production candidate прошёл
все восемь invariants (`all_pass=True`). Runtime и checks images собраны успешно.
Linux/Python 3.12 / PostgreSQL 16 повторил полный suite с exit 0: те же 198
application, 6/18/7/9 вспомогательных tests, format/lint/types, migration drift,
static build и frozen/candidate verifiers прошли. Этот локальный контейнерный
прогон проверяет изменённый application code; он не является hosted CI tested SHA.
Локальные подробные логи находятся в ignored `.artifacts/imp04-snapshot/`;
сохранённые application tests — воспроизводимый Git artifact.

## Adversarial review и границы доказанного

Автор отдельно проверил diff против audit exit criteria, acceptance, рисков,
границ транзакции и контрпримеров выше. Отдельный агент или внешнее ревью не
заявляются. Проверка поймала неполную старую fixture без observations и реальную
коллизию platform IDs в selector pool; обе причины устранены и проверены.
Переход generation к terminal сам по себе больше не принимается за evidence
полного snapshot. Тест crash проверяет откат Review, Observation, SourceFetch,
Corpus и SummaryJob, сохраняя предыдущую страницу и processed core candidate.

Дневной набор — согласованная локальная группа завершённых обходов, а не атомарный
снимок внешнего сайта. Изменение не посещённой повторно страницы на стороне
источника может остаться незамеченным при стабильных counts; source maximum и
production capacity не доказаны. Game lock сериализует запись одной игры, а
builder читает весь полный pool; большой corpus может задержать её следующие
коммиты. Малые concurrency tests и migration fixture не заменяют нагрузочные
измерения HRD/PUB.

Существующие R01/R07–R11/R13/R14/R18 и UI R12/R17/R21 остаются отдельными
corrections. В частности, этот цикл не доказывает полный payload budget,
attempt ledger, admission quota, redelivery fencing, порог после dedup или
правильное отображение cache hit/staleness в UI. Он проверяет создание/повторное
использование durable summary job, а качество и публикация provider output
проверяются собственными acceptance/eval задачами.
