# Аудит ворот G2 — снятие критической неизвестности

## Результат

**Ворота `G2` пройдены с принятыми ограничениями.** Все обязательные spikes `SPK-01–SPK-06` завершены решением `Proceed with limitation`; текущих `Blocked / Ask`, `Replan` и рисков приоритета `P0` нет. Можно переходить к стадии 3 и задаче `PLN-01`, но это решение ещё не выбирает стек и не разрешает начинать реализацию до прохождения `G3`.

## Проверенные spikes

| Spike | Решение и достаточное evidence | Остаточное ограничение, переданное дальше |
|---|---|---|
| `SPK-01` | `Proceed with limitation`: обе страницы Metacritic дали пригодный исходный HTML; владелец подтвердил разрешение на согласованный scope. [`metacritic-access.md`](../../research/feasibility/metacritic-access.md) | Условия, `robots.txt`, Cloudflare и допустимая частота могут измениться; подтверждение scope нужно сохранить перед release. |
| `SPK-02` | `Proceed with limitation`: подтверждены New Releases/SEE ALL, источники обязательных полей, platform-specific reviews и full/multiplatform/incomplete fixtures. [`metacritic-contract.md`](../../research/feasibility/metacritic-contract.md) | Недокументированная разметка и семантические ошибки источника требуют schema/failure/live contract checks. |
| `SPK-03` | `Proceed with limitation`: проверены `game-title.id`, platform IDs, `relatedGameId`, aliases, конфликты и ID-first update contract. [`game-identity.md`](../../research/feasibility/game-identity.md) | SSR IDs недокументированы; исчезновение или конфликт должны останавливать update до порчи данных. |
| `SPK-04` | `Proceed with limitation`: определены business day, batch, retry, restart, overlap и persistent state transitions. [`processing-state.md`](../../research/feasibility/processing-state.md) | Mutable source и конкретная atomic DB semantics требуют selector, recovery и concurrency tests. |
| `SPK-05` | `Proceed with limitation`: Groq Free / `openai/gpt-oss-20b`, `9/9` structural cases, rubric `96/98`, `0` blockers. [`ai-summary.md`](../../research/feasibility/ai-summary.md) | Free TPD покрывает около 77 изменившихся игр/день при наблюдаемом размере; принят extractive single-support режим, async queue и no-paid-fallback contract. |
| `SPK-06` | `Proceed with limitation`: Ubuntu VDS подтвердила public ingress, persistent state, process restart и реальное cron-событие. [`deployment.md`](../../research/feasibility/deployment.md) | Нужно выбрать supervision/TLS, проверить host reboot и два последовательных application schedule windows. |

## Аудит реестра рисков

В [`docs/risks.md`](../risks.md) находится 24 именованных риска: 20 Must и 4 изолированных Bonus. После spikes текущая приоритизация содержит 0 `P0`, 16 `P1`, 4 `P2` и 4 `B`. Каждый Must-риск имеет проверку, принятое решение или ограничение, митигацию, владельца следующего действия и остаточный риск.

| Risk | Решение на `G2` | Evidence | Остаточный риск | Следующее действие / владелец |
|---|---|---|---|---|
| `R-EXT-01` | `Proceed with limitation` | `SPK-01`, VDS check `SPK-06` | Второй route, частота, region/Cloudflare и структура могут измениться | Contract/failure и release live checks — `HRD-01/PUB-01` |
| `R-EXT-02` | `Proceed with limitation` в подтверждённом scope | Owner clarification и датированный `SPK-01` | Подтверждение не является repository artifact; Terms/scope изменяемы | Evidence index и финальная перепроверка условий — `REL-02` |
| `R-EXT-03` | `Proceed with limitation` | Field map и representative fixtures `SPK-02` | Новые варианты страниц и ошибочные source values | Boundary/failure tests — `HRD-01` |
| `R-EXT-04` | `Proceed with limitation` | Full/multiplatform/incomplete fixtures `SPK-02` | Fixtures не покрывают будущую разметку | Completeness/schema/live drift checks — `HRD-01` |
| `R-AI-01` | `Proceed with limitation` | Frozen eval `SPK-05`, `96/98`, no blockers | Нет доказательства надёжного abstractive cross-review synthesis; возможны пропуски/шум и language variants | Реализация и quality/failure regression — `IMP-04/HRD-04` |
| `R-AI-02` | `Proceed with limitation` | Live Groq access, token/latency/limit baseline `SPK-05` | Free TPD ниже cold-path maximum; quota/model/latency внешне изменяемы | Cache, persistent queue, backpressure, capacity state — `PLN-01/IMP-04/HRD-04` |
| `R-DEP-01` | `Proceed with limitation` | Public VDS capability `SPK-06` | Нет production supervision/TLS и host-reboot evidence | Выбор runtime и public validation — `PLN-01/PUB-01–PUB-02` |
| `R-DEP-02` | `Proceed with limitation` | Неавторизованный внешний HTTP check `SPK-06` | Финальные service/repository/archive URLs ещё не существуют | External link check — `REL-04` |
| `R-ID-01` | `Proceed with limitation` | Identity cases и transition contract `SPK-03` | SSR IDs могут исчезнуть, измениться или конфликтовать | Unique/upsert/conflict/concurrency tests — `IMP-01–IMP-02/HRD-02–HRD-03` |
| `R-TIM-01` | `Proceed with limitation` | State model и fake-time scenarios `SPK-04` | Mutable ordering не является source snapshot | Selector/state tests — `IMP-03/HRD-02` |
| `R-TIM-02` | `Proceed with limitation` | Restart/overlap transitions `SPK-04` | Atomic ownership зависит от выбранной БД и at-least-once scheduler | DB contract и recovery/concurrency tests — `PLN-02/HRD-02–HRD-03` |
| `R-DAT-01` | `Proceed with limitation` | Incomplete fixtures `SPK-02`, conflict cases `SPK-03` | Формально валидное, но семантически неверное значение | Non-destructive update tests — `HRD-01–HRD-02` |
| `R-SIM-01` | `Proceed to design with constraint` | Сохранённые признаки подтверждены `SPK-02` | Релевантность субъективна на малой базе | Explainable candidate — `PLN-02`; frozen oracle — `SIM-EVAL-01`; выбор метода — `IMP-06` |
| `R-OPS-01` | `Proceed with limitation` | Persistent cron event `SPK-06` | Один capability event не доказывает полный application outcome | Structured run records и два public windows — `HRD-05/PUB-02` |
| `R-TST-01` | `Proceed with mitigation` | Metacritic fixtures `SPK-02`, frozen AI cases `SPK-05` | Offline suite не доказывает текущие внешние contracts | Fake-provider/offline suite плюс отдельные live checks — `HRD-06` |
| `R-SEC-01` | `Proceed with mitigation` | Secret boundaries в `SPK-05–SPK-06`, repository policy | Scanner может не распознать новый секрет; внешний/AI-текст остаётся недоверенным | Security/escaping/secret checks — `HRD-05/REL-03` |
| `R-DEL-01` | `Proceed with mitigation` | Текущая история и sanitised evidence сохраняются по ходу | Платформа может не дать полный raw export | Manifest, privacy и completeness review — `REL-03` |
| `R-PLN-01` | `Proceed with limitation` | Must-first workflow и относительные оценки | Без дедлайна/ёмкости нельзя обещать календарный срок | Принять отсутствие или уточнить при rebasing — `PLN-03` |
| `R-REP-01` | `Proceed with mitigation` | Репозиторий содержит config templates и воспроизводимые spike-команды | Чистый production bootstrap ещё не проверен | Early scaffold и final clean-run — `IMP-01/REL-01–REL-02` |
| `R-UI-01` | `Proceed with mitigation` | `AC-UI-01–AC-UI-06` и edge-case oracles | Интеграционные и browser-варианты ещё не реализованы | Combined E2E/public smoke — `IMP-05/IMP-07/PUB-03` |

`Open — mitigate` после `G2` не означает, что риск исчез. Это означает, что неизвестность больше не опровергает план: выбран ограниченный путь, а остаток привязан к конкретной реализации или проверке до соответствующих ворот.

## Проверка условий G2

| Условие | Статус | Evidence |
|---|---|---|
| Нет критического риска без владельца и следующего действия | Выполнено | 20/20 Must risk blocks содержат check, mitigation, owner, residual risk и disposition; таблица выше |
| Есть реальный путь получения обязательных данных Metacritic | Выполнено с ограничениями | `SPK-01–SPK-03`, VDS HTTP check `SPK-06` |
| Identity игры и платформ однозначна для реализации | Выполнено с ограничениями | ID-first contract и conflict cases `SPK-03` |
| Время, batch, restart и overlap однозначно моделируются | Выполнено с ограничениями | Transition model `SPK-04` |
| AI имеет измеримый baseline, а не единичный пример | Выполнено с ограничениями | Frozen nine-case eval, rubric and scored report `SPK-05` |
| Публичная среда поддерживает обязательный эксплуатационный сценарий | Выполнено с ограничениями | Public/persistence/restart/cron probe `SPK-06` |
| Неразрешённые вопросы являются явными допущениями или design parameters | Выполнено | `assumptions.md`; `ASM-21` перенесён из spike в design/eval и остаётся candidate до независимого oracle |
| Bonus-риски не блокируют Must | Выполнено | Все четыре `R-BON-*` имеют приоритет `B`, статус `Deferred bonus`; Bonus расположен после `G6` |

## Переданные ограничения и stop conditions

- Если подтверждённый scope доступа Metacritic утрачен или live contract перестал работать, связанная работа становится `Blocked / Ask` либо `Replan`; обход ограничений запрещён.
- Если устойчивый AI change volume превышает доступную Free TPD capacity, нельзя скрытно включать оплату: требуется batching/model/provider `Replan` либо явное новое решение владельца.
- Если выбранная БД не даёт проверяемую atomic ownership/idempotency semantics, архитектура должна быть пересмотрена до `G3`, а не компенсирована надеждой на scheduler.
- Если VDS не поддержит production supervision/TLS или состояние после host reboot, public deployment нельзя считать проверенным до `G6`.
- Если similarity baseline не проходит заранее замороженный golden set, требование остаётся незавершённым; внешний AI/vector service не добавляется без отдельного обоснования.
- Bonus остаётся полностью отложенным до прохождения `G6`; его внешние неизвестные не расширяют Must scope.

## Следующий шаг

`PLN-01` получает статус `Ready`: выбрать минимальный стек и архитектурный контур с учётом перечисленных ограничений. В рамках `RSK-02` стек не выбирался, application source не создавался и стадия 3 не выполнялась.
