# Adversarial review `PLN-02`

- **Дата:** 2026-09-08
- **Решение:** `Changes requested`
- **Проверяемая задача:** `PLN-02`
- **Источники:** [`assignment.md`](../../assignment.md), [`acceptance.md`](acceptance.md), [`assumptions.md`](assumptions.md), [`docs/design.md`](../design.md), [`docs/risks.md`](../risks.md), [`action_plan.md`](../../action_plan.md)

## Результат проверки

| Область | Результат | Evidence / замечание |
|---|---|---|
| Module, persistence и transaction boundaries | Pass with implementation evidence deferred | Контракты описаны в `docs/design.md`; executable проверки явно принадлежат `IMP-02–IMP-04/HRD-01–HRD-04` и не считаются уже выполненными |
| Исходные отзывы и summary provenance | Pass at design level | Полный фактически полученный текст отделён от immutable model corpus; attempt хранит model/configuration/time/usage/outcome |
| Полнота review collection | Fail | Design ограничивался одной подтверждённой страницей; pagination, ordering, exhaustion, duplicates и reported-versus-fetched counts не были evidence-backed |
| Граница model input | Fail | Лимиты заданы characters/reviews, но provider ограничивает tokens/requests/time; production-maximum multilingual case не проверен |
| Выбор similarity policy | Fail | Формула и threshold были помечены `Accepted / 1.0.0` до golden set, метрики и порога, что противоречит `AC-SIM-03` |
| Инфраструктурная соразмерность | Pass | Для исправлений не нужны broker, vector DB, отдельный API/SPA или monitoring service |

## Контрпример similarity

При текущих весах кандидат без общего genre может получить `0.40` только за ту же platform и developer. Поэтому формула способна поставить его выше кандидата с частичным жанровым совпадением. Это не доказывает, что формула неверна, но доказывает, что она не может быть принята без заранее зафиксированного quality oracle.

Правильный порядок:

1. `SIM-EVAL-01` фиксирует examples/golden set, labels, metric, threshold и hard invariants.
2. `IMP-06` реализует candidate `0.1.0` и минимум один простой baseline, сравнивает их без изменения oracle и выбирает простейший прошедший вариант.
3. `SIM-VER-01` отдельно проверяет database/UI integration, детерминированность, малую/пустую базу и переход к правильному game ID.

## Условия повторной проверки

- source-contract evidence подтверждает pagination/cursor, ordering, exhaustion, duplicates и coverage counts отдельно для critic/user routes;
- corpus policy использует token-aware preflight и проходит production-maximum multilingual boundary case;
- непроверенные review/AI и similarity policies остаются `Candidate`;
- каждый критерий выхода `PLN-02` сопоставлен независимому evidence либо явно принятому ограничению;
- повторный adversarial review не содержит нерешённых материальных замечаний.

До выполнения этих условий `PLN-02` не получает `Verified`, а `PLN-03` остаётся `Planned`.
