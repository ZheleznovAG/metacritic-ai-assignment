# План действий: master tracker

- Baseline: **1.0**, задача `PLN-03`, 2026-09-09 (Asia/Novosibirsk).
- Bonus scope: `pending`.
- IMP-01, IMP-02, IMP-03 verified. Последний завершённый цикл — IMP-03 (batch/calendar cycle, реальный scheduler).
- Текущий blocker: нет. IMP-04 ожидает REV-EVAL-01 (уже Ready, независимый); SIM-EVAL-01 также доступен независимо.

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

## Приоритет следующего цикла

`IMP-01` закрыт независимым adversarial review в отдельной сессии ([imp_01_independent_review.md](docs/requirements/imp_01_independent_review.md)): все заявленные exit criteria (build/tests/security posture, hosted CI run [34574112620](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34574112620), VDS redeploy) воспроизведены заново в этой сессии с идентичным результатом; найдена и исправлена одна тривиальная документационная неточность (устаревшая строка в README.md).

`IMP-02` закрыт ([imp_02_review.md](docs/requirements/imp_02_review.md)): реальный multiplatform game (Elden Ring) прошёл end-to-end от живого источника через непрозрачный `(source, source_game_id)` upsert до публичной read-only карточки; sanitised HTML/SSR fixtures и независимые expected values построены до parser; non-destructive merge, естественный `null` (Xbox One/PlayStation 4 Metascore) и атомарность core/job intent (forced rollback test) проверены; пять последовательных живых запуска против реального сайта подтвердили idempotency без дублей. Три раунда adversarial review — собственный `/code-review high` и два прохода независимой проверки кода отдельной параллельной сессией (`metacritic-ai-assignment-dc`), не запрошенной этой сессией, включая повторную проверку уже применённого исправления — нашли и закрыли семь реальных дефектов (несинхронизированный `source_game_platform_id`, `javascript:`-URL без проверки схемы, отсутствие проверки canonical/og:url против misrouted fetch, выбор первой попавшейся `game-title` записи вместо совпадающей по slug, потерянная provenance для fanned-out platform fetches, blank-string не защищённый non-destructive merge, provenance-указатель на неудавшийся fetch при сохранённом старом значении — закрыт разделением `last_changed_fetch` на отдельные Metascore/Userscore поля) до коммита; один known limitation (деградация extraction неотличима от естественного отсутствия) задокументирован для `HRD-01`. `IMP-03` теперь `Ready`; независимые циклы `REV-EVAL-01`/`SIM-EVAL-01` остаются доступны параллельно.

`IMP-03` закрыт ([imp_03_review.md](docs/requirements/imp_03_review.md)): полная модель состояний `SPK-04` (`ProcessingLease`/`ProcessingRun`/`CoreAttempt`, реальный `DailyCycle`/`DailyCandidate` state machine) реализована; Selector детерминированно покрывает 11 из 12 paper scenarios `SPK-04` (`PS-11` — AI failure — структурно тривиален до `IMP-04`; `PS-12` — non-UTC timezone — не реализован, UTC default `ASM-01` эксплицитно достаточен). Реальный scheduler (`scripts/run_scheduler.py`, отдельная `SCHEDULER_DB_USER` роль) трижды подряд сработал точно на реальной часовой границе без вмешательства (12:00, 13:00 и 14:00 UTC), real retry двух подлинных transient-сбоев сети (не смоделированных) и real same-hour idempotency (skipped_duplicate без лишних HTTP). Живая проверка нашла и закрыла один реальный баг парсера, обнаруженный собственным вторым запуском scheduler'а: canonical-проверка SEE ALL страниц ошибочно требовала точное совпадение `?page=N`, хотя реальный источник canonicalизирует все страницы листинга к одному base URL независимо от номера страницы (подтверждено на трёх реальных снимках: page 1/2/7429); фикс — path-only проверка только для browse-листинга, строгая проверка для game-detail/platform страниц не тронута; процесс перезапущен с фиксом после второго запуска, и уже третий запуск (14:00 UTC) прошёл с фиксом автоматически — `browse_page` успешно получена, курсор продвинулся, статус `succeeded` — так фикс подтверждён не только прямым live-вызовом парсера, но и реальным automated tick. Финальный adversarial self-review (отдельный fork-проход по всему diff) нашёл второй реальный баг до коммита: `Selector.run_batch` ошибочно классифицировал batch, где отказали вообще все элементы, как `partial` вместо `failed` (расходится с таблицей статусов `SPK-04`); исправлено, добавлен регрессионный тест. `IMP-04` остаётся `Planned` в ожидании `REV-EVAL-01`; независимые циклы `REV-EVAL-01`/`SIM-EVAL-01` остаются доступны параллельно.

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
| [IMP-01](implementation_plan.md#imp-01) | G3 | base | Verified | [Scaffold/local tests/public preview](docs/requirements/imp_01_review.md), [tooling correction and VDS redeploy](docs/requirements/imp_01_correction.md), [independent adversarial review](docs/requirements/imp_01_independent_review.md); hosted CI passed [run 34574112620](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34574112620) at `6d29461`; corrected candidate redeployed and externally smoked on VDS |
| [IMP-02](implementation_plan.md#imp-02) | IMP-01 | base | Verified | [Fixtures/parser/upsert/card evidence](docs/requirements/imp_02_review.md); пять живых запусков против реального сайта, idempotent; три раунда adversarial review (self + два прохода независимой параллельной сессии) |
| [IMP-03](implementation_plan.md#imp-03) | IMP-02 | base | Verified | [Selector/scheduler/lease evidence](docs/requirements/imp_03_review.md); три реальных последовательных hourly-запуска, restart, найденный и исправленный live-баг canonical-проверки, подтверждённый третьим automated tick |
| [REV-EVAL-01](implementation_plan.md#rev-eval-01) | G3, SPK-05 | base | Ready | Ожидается: evals/review_selection: dataset/rubric/acceptance |
| [IMP-04](implementation_plan.md#imp-04) | IMP-03, REV-EVAL-01 | base | Planned | Ожидается: Review fixtures, tests, selection/summary/capacity reports |
| [IMP-05](implementation_plan.md#imp-05) | IMP-04 | base | Planned | Ожидается: UI checks/screenshots и public smoke |
| [SIM-EVAL-01](implementation_plan.md#sim-eval-01) | G3 | base | Ready | Ожидается: evals/similarity: dataset/metric/acceptance |
| [IMP-06](implementation_plan.md#imp-06) | SIM-EVAL-01, IMP-02 | base | Planned | Ожидается: Frozen comparison report и policy version |
| [SIM-VER-01](implementation_plan.md#sim-ver-01) | IMP-05, IMP-06 | base | Planned | Ожидается: Integration/E2E и relevance regression |
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
