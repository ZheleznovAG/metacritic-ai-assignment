# Adversarial review `PLN-02`

- **Дата:** 2026-09-08
- **Решение:** `Verified` после исправлений и повторной проверки
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

Нерешённых материальных замечаний на уровне design/contract нет. `PLN-02` получает `Verified`; это не подменяет implementation evidence в `IMP-02–IMP-04/HRD-01–HRD-04` и не принимает quality-sensitive selection/similarity методы до `REV-EVAL-01`/`SIM-EVAL-01`.
