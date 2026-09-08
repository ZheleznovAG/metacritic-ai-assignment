# Adversarial review `PLN-02`

- **Дата:** исходное review 2026-09-08; корректировка завершена 2026-09-09 (Asia/Novosibirsk)
- **Решение:** `Verified` на уровне design после последующей корректировки retry/storage/evidence
- **Проверяемая задача:** `PLN-02`
- **Источники:** [`assignment.md`](../../assignment.md), [`acceptance.md`](acceptance.md), [`assumptions.md`](assumptions.md), [`docs/design.md`](../design.md), [`docs/risks.md`](../risks.md), [`action_plan.md`](../../action_plan.md)
- **Независимые evidence:** [`metacritic-contract.md`](../../research/feasibility/metacritic-contract.md), [`reviews-pagination.json`](../../research/feasibility/fixtures/metacritic/reviews-pagination.json), [`check_token_budget.py`](../../evals/reviews/check_token_budget.py), [`token-budget-report.json`](../../evals/reviews/token-budget-report.json)

## Результат проверки

| Область | Результат | Evidence / замечание |
|---|---|---|
| Module, persistence и transaction boundaries | Pass with implementation evidence deferred | Контракты описаны в `docs/design.md`; executable проверки явно принадлежат `IMP-02–IMP-04/HRD-01–HRD-04` и не считаются уже выполненными |
| Исходные отзывы и summary provenance | Pass at design level | Каждый полученный review сохраняется полностью на исходном языке; complete source snapshot отделён от immutable bounded model corpus; attempt хранит model/configuration/time/token usage/outcome |
| Полнота review collection | Pass with external-change/storage limitation | Независимый controlled crawl подтвердил backend `links.next`, source order, exhaustion, counts и отсутствие дублей: user `393/393`, critic `86/86`. Web `?page=N` доказанно повторял первую страницу; design его запрещает. Route с `1,557` отзывами подтверждает page-bounded processing; глобальный maximum неизвестен, поэтому total не capped, а storage envelope отложен в `HRD-05/PUB-02`. Evidence: [`reviews-pagination.json`](../../research/feasibility/fixtures/metacritic/reviews-pagination.json) |
| Граница model input | Pass for candidate maximum | `o200k_harmony` preflight проверил 10 multilingual reviews × 450 tokens: guarded prompt `5,559`, reservation `6,359 < 8,000 TPM`; live usage `5,493 + 240 = 5,733`. Evidence: [`token-budget-report.json`](../../evals/reviews/token-budget-report.json) и воспроизводимый checker |
| Выбор bounded review sample | Pass for evidence ordering | Selection больше не зависит от first page и детерминирована по полному snapshot, но остаётся Candidate: `REV-EVAL-01` замораживает examples/metric/threshold/invariants до comparison в `IMP-04`; `HRD-04` проверяет регрессию |
| Выбор similarity policy | Pass for evidence ordering | Формула помечена только `Candidate 0.1.0`; `SIM-EVAL-01` замораживает oracle до comparison в `IMP-06`, а `SIM-VER-01` проверяет интеграцию после выбора |
| Инфраструктурная соразмерность | Pass | Для исправлений не нужны broker, vector DB, отдельный API/SPA или monitoring service |

## Повторные adversarial scenarios

| Сценарий | Требуемое поведение | Контракт / evidence |
|---|---|---|
| `?page=2` возвращает те же 50 cards | Не считать это второй страницей; использовать только validated backend `next` | Наблюдалось на пяти значениях `page`; внешний fixture |
| Backend повторяет cursor/page identities | Generation становится `unstable`, summary не обновляется | Visited-cursor/page fingerprint invariants в design |
| Ошибка после нескольких успешных pages | Страницы остаются сохранёнными, cursor не продвигается мимо сбоя, новый corpus не создаётся | Page-level atomic commit и terminal snapshot rule |
| Reported total меняется во время обхода | Не заявлять полноту; завершить `unstable` и повторить позже | Stable-total/unique-count exit condition |
| Route содержит 1,557+ отзывов | Обрабатывать по одной странице без загрузки route целиком в RAM и без AI call на страницу | Volume probe и существующий PostgreSQL job/worker contour |
| Изменился только review вне bounded sample | Обновить source coverage fingerprint, но не тратить AI quota при неизменном exact input | Раздельные source-set/input fingerprints |
| Кириллица/CJK/Arabic/emoji дают больше tokens на character | Обрезать по tokenizer boundary, считать весь request и fail closed до внешнего вызова | Multilingual maximum local/live check |
| Candidate similarity лучше по формуле, но хуже для человека | Не менять oracle после результата; policy не принимать без threshold | `SIM-EVAL-01 -> IMP-06 -> SIM-VER-01` |

## Контрпример similarity

При текущих весах кандидат без общего genre может получить `0.40` только за ту же platform и developer. Поэтому формула способна поставить его выше кандидата с частичным жанровым совпадением. Это не доказывает, что формула неверна, но доказывает, что она не может быть принята без заранее зафиксированного quality oracle.

Правильный порядок:

1. `SIM-EVAL-01` фиксирует examples/golden set, labels, metric, threshold и hard invariants.
2. `IMP-06` реализует candidate `0.1.0` и минимум один простой baseline, сравнивает их без изменения oracle и выбирает простейший прошедший вариант.
3. `SIM-VER-01` отдельно проверяет database/UI integration, детерминированность, малую/пустую базу и переход к правильному game ID.

## Результат повторной проверки

- [x] Source-contract evidence подтверждает pagination/cursor, ordering, exhaustion, duplicates и coverage counts отдельно для critic/user routes.
- [x] Corpus policy использует token-aware preflight и проходит production-maximum multilingual boundary case локально и у provider.
- [x] Непроверенные bounded selection и similarity policies остаются `Candidate`.
- [x] Каждый критерий выхода `PLN-02` сопоставлен независимому evidence либо явно принятому ограничению.
- [x] Контрпримеры не требуют новой инфраструктуры и выражены будущими executable checks.

Первый повторный review закрыл pagination/token/similarity findings. Последующая проверка обнаружила дополнительные замечания ниже; поэтому первоначальное заключение об отсутствии материальных design findings было пересмотрено. Implementation evidence и quality-sensitive selection/similarity по-прежнему принадлежат будущим задачам.

## Последующая корректировка retry, storage и evidence

| Finding | Исправление / проверка | Граница доказательства |
|---|---|---|
| Failed fetch занимает unique key страницы и конфликтует с retry | Отдельная identity попытки и partial uniqueness только принятой страницы; terminal history не переписывается. PostgreSQL SQL-probe воспроизводит старый конфликт и проверяет исправленный ключ | Проверены PostgreSQL constraints/rollback; реальный worker, fencing и concurrency ещё не реализованы |
| Crash между core success и созданием enrichment jobs может потерять работу | Запись `processed` и durable jobs входит в одну транзакцию; сетевой enrichment происходит после commit. SQL-probe проверяет rollback обеих записей | Реальные Django transaction/crash tests — `IMP-02/IMP-04/HRD-02–HRD-03` |
| `O(unique reviews)` не учитывает ежедневные observations | Модель включает text versions, observations всех generations, attempts, corpus, indexes/WAL/backup. SQL-probe даёт одну text version и две observations для двух обходов | Bytes/row, horizon и 80 GB capacity не доказаны; `HRD-05/PUB-02` |
| Queue/cache приняты без подтверждённого drain rate | Уточнён арифметический envelope: 154 jobs/day по среднему девяти cases; 31 при reservation измеренного boundary case; 29 при policy ceiling. Cold/unchanged/changed/quota scenarios назначены `IMP-04`, regression — `HRD-04`, реальные замеры — `PUB-02` | Это известное ограничение, не production throughput и не принятое latency SLO; `R-AI-02` остаётся открытым |
| Оценка `96/98` доступна только как сводка | [Published baseline](../../evals/reviews/baseline/README.md) содержит исходные canonical outputs, scores, notes и timestamps; `--verify` повторно проверяет формат, exact coverage, hashes, applicability, totals и арифметику rubric | Исходные ручные семантические оценки не заменяются новым автоматическим суждением; автор оценок в исходном файле не указан |
| Parser input fixtures отложены позже первого среза | HTML/SSR fixtures и expected extraction нужны до parser в `IMP-02`; review page/cursor fixtures — в `IMP-04`; `HRD-01` расширяет набор | Исправлена зависимость; исполняемый application parser ещё не существует |
| Intake ссылается на отсутствующий commit | `git log -- assignment.md` и `git show -s 7ce2ff8` подтверждают `7ce2ff88f9f946b4ce6d03d486c7f5fc2e44da12` и прежнее время; SHA-256 исходника совпадает | Исправлена ссылка; исходное задание не изменялось |

## Воспроизводимые проверки корректировки

Из корня репозитория, без `.env`, credentials или live AI:

```powershell
python -B evals/reviews/score_run.py evals/reviews/baseline/run.json --verify
python -B -m unittest discover -s evals/reviews -p "test_*.py" -v
git diff --check
```

PostgreSQL constraint prototype, на отдельной PostgreSQL 16 с обычными параметрами подключения `psql`:

```powershell
psql -X -v ON_ERROR_STOP=1 -f research/feasibility/probes/pln02_review_attempts.sql
```

Проверено 2026-09-08 UTC на PostgreSQL `16.15` в отдельном временном контейнере с `--network none`, без открытых портов и постоянных volumes; данные в tmpfs. Image digest: `sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`. Результат: `PASS` для old-key counterexample, retry history, unique success, immutable terminal, page/core rollback и observation growth; итоговый `ROLLBACK`. Контейнер после проверки остановлен и автоматически удалён; существующие контейнеры не менялись. Probe использует временные таблицы и не является production migration или concurrency test.

Offline verifier дал `96/98 (97.96%)`, все 7 integrity tests прошли, включая удалённый/дублированный case, подменённый support, N/A у критического критерия, неверные hash и aggregate. Публикационные JSON значения сравнены с локальными оригиналами: run совпадает полностью; scorecard отличается только путём run и двумя добавленными fingerprints. Исходные scores/notes/timestamps не редактировались. Ни одного нового inference request не выполнено.

Матрица выше дополняет исходную проверку всех exit criteria `PLN-02`: design constraints и доступность evidence проверяются сейчас; application capacity, parser integration, queue/concurrency и quality policies не объявляются доказанными этой корректировкой.

Проверка из отдельного снимка Git index также прошла: все tracked files выгружены через `git checkout-index` без `.env`, `.venv` и `.eval-runs`; внешний локальный Python `3.14.7` выполнил `--verify` и 7 integrity tests на файлах снимка. Это подтверждает доступность baseline из клона без приватных артефактов; canonical application runtime Python 3.12 остаётся задачей `IMP-01`.

Заключительный adversarial review проверил повтор одной страницы после ошибки, late response после reclaim, двойное принятие страницы, rollback cursor/core/jobs, повтор неизменного корпуса, искусственное улучшение eval удалением case или N/A, различие measured reservation и policy ceiling, а также порядок `IMP-02/IMP-04 -> HRD-01/HRD-04 -> PUB-02`. Материальных замечаний к исправленным design boundaries и публикации evidence не осталось. `PLN-02` получает `Verified`; `PLN-03` становится `Ready`. Риски capacity/storage и непроверенные quality policies сохраняют свои явные ограничения и будущие проверки; `G3` этим циклом не закрывается.
