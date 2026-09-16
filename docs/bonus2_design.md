# Bonus 2: кандидат контракта мониторинга и запуска

Дата: 2026-09-16. **Candidate** для `BON-21`/`BON-22`; это проект проверяемого
поведения, не evidence реализации. Выбор ветки принят в [ADR-0002](decisions/0002-bonus2-scope.md).
Текущие статусы/зависимости — в [tracker](../action_plan.md), работы/оценки — в
[плане](../implementation_plan.md#bon-21). Контракт дополняет [design.md](design.md)
только после проверки соответствующего среза.

## Проверенная исходная точка

Основание — чтение кода на `ce777b9`; продуктовые тесты в этом planning-цикле
не запускались.

| Что есть | Следствие для реализации |
|---|---|
| [ProcessingRun, CoreAttempt, DailyCycle](../app/processing/models.py) | История и дневной прогресс уже persistent; нужны live-проекция и тип manual trigger |
| [run_tick](../app/processing/scheduler.py) и [lease](../app/processing/lease.py) | Scheduled trigger dedup, fencing и recovery переиспользуются; текущий entry point принимает только часовой slot |
| [selector](../app/processing/selector.py), [runner](../app/processing/runner.py) | `selected_count` записывается до цикла; processed/failed — при закрытии run, отдельные CoreAttempt коммитятся по ходу |
| [diagnostics](../app/processing/diagnostics.py) | Есть read-only CLI-проекции run/job/backlog; общего согласованного web snapshot и process heartbeat нет |
| [scheduler loop](../app/processing/management/commands/run_scheduler.py), [worker loop](../app/reviews/management/commands/run_worker.py) | Интервалы idle polling 20/5 секунд; HTTP выполняется синхронно, поэтому heartbeat только между tick недостаточен |
| [settings](../app/config/settings.py), [DB provisioning](../scripts/provision_db.py) | Auth/session apps отсутствуют; web имеет SELECT, scheduler/worker — широкие DML grants; новые auth-таблицы требуют пересмотра default grants |
| [compose.yaml](../compose.yaml), [role tests](../scripts/tests/test_database_roles.py) | Supervision и ограниченные контейнеры уже есть; роли проверяются на настоящем PostgreSQL |

## Пользовательский результат

Публичная страница `/ops/` по ссылке из общей навигации показывает scheduler
и enrichment worker, текущую работу, последний результат, историю последних
20 запусков и очереди отзывов/AI. Подписи — English по `ASM-14`; время UTC
показано явно. Счётчики игр, review jobs и summary jobs имеют отдельные единицы.

Кнопка **Run processing** доступна после входа оператору с правом запуска.
После клика виден идентификатор запроса, затем связанный run и его результат.
Публичный пользователь может наблюдать обработку; имена операторов и сведения
доступа публично не раскрываются. Статус core `succeeded` не означает, что
асинхронные отзывы и AI уже завершены.

Перезапуск воркеров/контейнеров, редактирование каталога, сброс дневного прогресса,
принудительная регенерация AI, произвольные команды/URL и отмена работ не входят
в эту кнопку. Один принятый запуск обрабатывает обычную партию до 20 кандидатов.

## Мониторинг: источник истины и свежесть

Предлагается обычный JSON snapshot `GET /ops/status/` и polling раз в 1 секунду
в открытой активной вкладке. Это соответствует существующему WSGI без нового
сервиса. `Cache-Control: no-store`, один запрос в полёте, ограниченный timeout;
после ошибки — backoff до 2 секунд, после возврата связи/focus — немедленный
snapshot. Старый ответ не может заменить более новый. При выключенном JS
доступен серверный snapshot с явной датой и ручным обновлением.

- `ASM-B03`: committed server change появляется в подключённой активной вкладке
  не позднее 5 секунд. В тесте сравниваются commit и browser observation на
  одной шкале времени; часы клиентского компьютера не являются оракулом.
- После 5 секунд без успешного snapshot UI показывает **Connection lost / data
  may be stale**, сохраняет последние значения и timestamp. Не создаёт локальный
  прогресс и не переводит server run в failed. После reconnect предел 5 секунд
  применяется от восстановления связи. Фоновая/приостановленная вкладка помечает
  старые данные при возвращении и сразу запрашивает новые.
- Ответ включает `snapshot_at`, business date/timezone, process observations,
  run IDs/statuses/counters и отдельные backlog counts. Несколько запросов внутри
  snapshot читают одну согласованную DB-версию (короткая read-only транзакция
  REPEATABLE READ); сеть/LLM внутри неё не вызываются.
- Пока run активен, processed/failed считаются по сохранённым CoreAttempt данного
  run; selected — по замороженной партии. После recovery одна игра может иметь
  несколько attempts: live-проекция и финал используют одну явно проверенную
  семантику уникальных кандидатов с последним outcome. Принадлежность кандидатов
  партии нужно сохранять до первого HTTP (например, `RunCandidate` с unique
  run/candidate); resume продолжает эту партию и оставшийся бюджет, а не выбирает
  ещё 20 игр для прежнего run. Attempts отображаются отдельно. Проверяется
  `processed + failed <= selected <= 20`; незавершённый
  candidate не объявляется failed только из-за отсутствия ответа.
- «Found today» — уникальные DailyCandidate текущего UTC-дня, включая ещё не
  выбранные; «Selected in run» — кандидаты данной партии. Эти величины могут
  отличаться. Сравнение финала выполняется с persistent run record.
- Очереди показывают текущие pending/running/retry/delayed/failed/unstable и возраст
  ожидания; terminal history имеет отдельный scope. Daily/run counters не
  суммируются с review/AI counts. Неизвестный total не превращается в процент.

### Состояния процессов

Добавить persistent `ProcessHeartbeat`: логическая роль/slot, instance UUID,
generation, started/last_seen/last_progress, режим idle/busy/stopping, текущий
run/job ID и стадия. На один slot хранится актуальная запись; новый instance
увеличивает generation, поздняя запись старого instance отклоняется.

Heartbeat записывается раз в секунду отдельным коротким циклом с собственным
DB connection; долгий Metacritic/Groq вызов не блокирует его. До первой записи —
`unknown`, heartbeat старше 3 секунд — `stale`; при штатной остановке — `stopped`.
При polling 1 с и времени ответа до 1 с потеря heartbeat видна не позже 5 с от
последнего heartbeat. Это детектор отсутствия сигнала, не доказательство смерти
процесса. Пропавший heartbeat не отзывает ProcessingLease и не разрешает дубль.

Живой heartbeat при зависшей основной работе не маскирует остановку прогресса:
показываются last_progress и стадия; превышение deadline соответствующей HTTP/job
операции отмечается отдельно как overdue. Lease expiry, process liveness и
terminal run outcome остаются разными состояниями. Проверяется продолжение
heartbeat при искусственно заблокированном HTTP, а не только idle-loop.

Нагрузка для приёмки: snapshot <=1 с на 10 одновременно открытых вкладках
(10 req/s), история ограничена 20 runs, ответ <=64 KiB, число ORM-запросов не
зависит от числа отображённых игр/jobs. Проверка на disposable PostgreSQL с
10 000 runs и 100 000 job records; измерить query plan, CPU/RAM и поведение
обычного каталога под polling. Если предел не достигнут, исправить запросы/индексы
до принятия транспорта, не ослаблять 5-секундную свежесть.

## Принудительный запуск: общий путь

Поток: browser POST → durable `ManualRunRequest` → scheduler admission → общий
lease/selector/core commit → существующие review/summary queues → monitoring.
HTTP не исполняет batch и не получает credentials фоновых ролей или Groq.

Предлагаемые изменения схемы: `ProcessingRun.trigger_kind=scheduled/manual`,
`scheduled_slot` nullable только для manual; unique trigger key сохраняется.
`ManualRunRequest` содержит UUID/idempotency key, operator ID, created_at,
state queued/claimed/completed/conflict/expired, nullable run ID, reason code.
Один принятый запрос связан максимум с одним run. Новые таблицы служат командой
и аудитом; логи приложения не являются очередью.

| Случай | Результат |
|---|---|
| Разрешённый новый POST с валидным UUID key | `202`, request ID; ответ только после commit |
| Повтор того же key, в том числе после timeout/reload | `200`, тот же request/run, без нового HTTP к источнику |
| Неверный payload/key | `400`; клиент не задаёт batch size, trigger kind или source URL |
| GET на команду | `405`, без изменения состояния |
| Anonymous / нет права / CSRF не прошёл | JSON `403`, без постановки и внешних вызовов |
| Другая активная/queued core-работа | `409 busy` со ссылкой на доступный run; в очередь «на потом» не добавляется |
| Исчерпан лимит ручных запусков | `429` + Retry-After, без новой работы |
| БД/сервис admission недоступен | `503`; UI сохраняет key для безопасного повтора |

Admission под общей транзакционной блокировкой проверяет idempotency раньше
cooldown/busy, затем активную работу и лимиты; DB constraint запрещает несколько
outstanding manual requests. Предложенный предел — один новый ручной запрос
за 5 минут и не более 6 за скользящий час на весь сервис, независимо от числа
операторов и web-процессов. Повтор принятого key лимит не расходует.

Общая блокировка принадлежит отдельной singleton-строке `TriggerAdmission`,
доступной web и scheduler на UPDATE. Web не блокирует `ProcessingLease` через
`SELECT FOR UPDATE`, для которого потребовалось бы расширение её прав. Все
scheduled/manual admission и recovery соблюдают один порядок блокировок:
admission → request/run → lease. Состояние lease web только читает, а scheduler
изменяет под той же admission-блокировкой. POST не удерживает её во время сети.
Повтор key другого оператора отклоняется без раскрытия чужого audit; известный
key своего запроса проверяется до busy/rate limits.

Scheduler проверяет queued commands не реже раза в секунду. Регистрация текущего
scheduled slot и manual admission отделяются от долгого core execution: часовой
таймер продолжает работать, даже если manual batch выполняется через границу
часа. Возможный механизм в том же scheduler-процессе — отдельный короткий
dispatcher cycle с собственным DB connection; общий execution остаётся один.

На одновременной границе часа due scheduled intent имеет приоритет. Если он
выиграл после HTTP `202`, запрос получает наблюдаемый `conflict`, а не скрытый
отложенный повтор. Если manual уже выполняется, scheduled slot всё равно
регистрируется и получает обычный `skipped_overlap`. Ручной запрос никогда
не использует `scheduled:<hour>` и не отменяет будущие scheduled slots (`ASM-02`).
Одного disabled button для сериализации недостаточно: два scheduler и два web
проверяются на PostgreSQL с barriers.

Создание manual run, связь с request и получение lease атомарны; исполнение
и terminal closure переиспользуют общий service, извлечённый из `run_tick`.
Crash после commit до ответа повторно выдаёт тот же request; crash после claim
до HTTP восстанавливает тот же run по ownership/fencing. Recovery просматривает
не только текущий scheduled slot, но и незавершённый manual run. До истечения
действующей lease второй исполнитель не начинает работу.

Queued request без начала исполнения истекает через 5 минут: после долгого
простоя внезапный пользовательский запуск не выполняется. Claimed request
восстанавливается как уже начатая работа. Idempotency/audit records сохраняются
в пределах retention run history; удаление ключа не допускает старый replay —
политику tombstone/срока допустимого key зафиксировать до добавления purge.

Manual использует business day начала исполнения и обычные retry-first,
лимит 20, дневной dedup, source exhaustion, review handoff и AI quota. После
полуночи применяются те же правила захвата даты, что для scheduled; кнопка
не означает повтор всех уже обработанных сегодня игр. Пустая exhausted партия
заканчивается честным результатом 0, без искусственной новой работы.

## Доступ оператора и права БД

Предложение для `ASM-B04`: стандартные Django auth + DB-backed sessions,
отдельное permission `processing.trigger_run`, отдельная страница входа и
POST logout; публичной регистрации и admin UI нет. Аккаунт без superuser
создаётся отдельной management-командой под migration/операторской ролью,
пароль передаётся приватно и не включается в docs/evidence.

Django предоставляет accounts/permissions и session integration; DB sessions
требуют session app/table. Штатный auth не включает throttling попыток входа:
это отдельная работа. Основание проверено 2026-09-16 по документации
[auth](https://docs.djangoproject.com/en/5.2/topics/auth/),
[permissions/login](https://docs.djangoproject.com/en/5.2/topics/auth/default/),
[sessions](https://docs.djangoproject.com/en/5.2/topics/http/sessions/).

Для кандидата: HTTPS, HttpOnly/Secure/SameSite cookies, CSRF на login/logout/run,
8-часовая session, проверка permission на каждый POST, прекращение доступа после
logout, disable account или отзыва права. Generic login errors; DB-backed
throttling — максимум 5 неуспешных попыток за 15 минут на account fingerprint
и отдельно на доверенный client IP. IP берётся только из настроенной цепочки
Caddy; присланному клиентом произвольному forwarding header доверять нельзя.

Нужна явная миграция permission boundary из ADR-0001: web по-прежнему не пишет
в catalog/reviews/summaries, ProcessingRun, CoreAttempt или heartbeat. Ему
разрешены только sessions, вставка manual request, изменение admission/rate-limit
служебных строк и необходимое поле `auth_user.last_login`; request outcomes
пишет scheduler. Права на пользователей/пароли/permissions web не получает.
Учесть автоматическое обновление password hash при login: либо узкая проверенная
операция, либо отключение такого обновления в web и отдельный upgrade-командой;
не выдавать blanket UPDATE на `auth_user`.

Текущие `GRANT ... ON ALL TABLES` и default grants нельзя механически распространить
на новые auth/session tables: scheduler/worker не должны менять пользователей,
права и сессии. Provisioning после migrations задаёт явную allowlist по ролям,
включая sequences; migration role остаётся единственным владельцем/DDL actor.
Reprovision повторяем, новые таблицы по умолчанию закрыты. Проверяются реальные
SQL denied/allowed paths, включая попытку background role выдать себе permission.

Public snapshot содержит allowlist агрегатов, статусов и нормализованных error
codes. В него не попадают stack traces, API responses, review text, cookies,
DB metadata, credentials, operator IDs или raw login/IP audit. UI экранирует
недоверенные title/error values; audit ограничен по объёму и не пишет пароли.

## Проверки перед принятием

Это будущие артефакты, не существующее acceptance evidence. CI использует
fake clock/gateway/provider и disposable PostgreSQL; никакие платные/live calls
не входят в автоматический suite.

| Проверка | Acceptance / risk | Ожидаемый независимый оракул |
|---|---|---|
| Смена queued/running/partial/succeeded/failed и skipped outcomes, refresh/reconnect | `AC-OPS-01`, `R-BON-OPS-01` | Commit timestamps и DB rows против Chromium DOM; каждая смена <=5 с |
| Счётчики до финала, retry/recovery, zero batch, смена UTC-дня | `AC-OPS-02`, `R-BON-OPS-01` | Контролируемые результаты кандидатов, число уникальных игр и terminal ProcessingRun |
| Heartbeat при idle, долгом HTTP, kill/restart, поздней записи старого instance | `OPS-01`, `AC-OPS-01` | Управляемый clock + реальные процессы/DB; stale не снимает lease |
| Slow/out-of-order response, разрыв сети, отказ БД, нагрузка | `AC-OPS-01`, `R-BON-OPS-01` | Stale banner, snapshot timing/size/query count, сохранность обычного UI |
| Anonymous, нет permission, отозванный доступ, CSRF, GET, login throttling | `AC-OPS-03`, `R-BON-OPS-02` | Ноль новых requests/runs/external calls; проверка session invalidation |
| Двойной click/key, разные keys/tabs/operators, replay после ответа/timeout/рестарта | `AC-OPS-03`, `NFR-03` | Один admission/run; атомарный cooldown на реальных конкурентных connections |
| Scheduled/manual race, запуск через час/полночь, два dispatchers | `AC-OPS-03`, `RUN-01`, `NFR-03` | Отдельный scheduled key, один lease owner, прежний daily limit и будущий hourly tick |
| Crash до/после request commit, claim, core commit; stale owner | `AC-OPS-03`, `NFR-02/03` | Тот же request/run, fencing, отсутствие повторных core commits и потерянного handoff |
| SQL role boundaries, secret/error exposure, XSS | `NFR-06`, `R-BON-OPS-02` | Реальные разрешённые/запрещённые SQL statements и негативные browser/API assertions |
| Публичный operator journey и анонимный monitoring | `AC-OPS-01/02/03`, `GB` | Versioned image + CI SHA, реальные run/counters, screenshots desktop/mobile и sanitized timing log |

Публичная проверка проводится после clean install и upgrade rehearsal, backup
и проверки отключения Bonus. Отдельные flags для monitoring/manual control
позволяют отключить новые endpoints; отключение ручного admission не теряет
claimed работу и не останавливает scheduled/worker loops. Rollback приложения
оставляет additive schema совместимой с Must и восстанавливает прежние grants
из проверенного runbook. Повторно проверить каталог, AI/similarity и очередной
реальный scheduled window после manual run. Неполный Bonus не получает `GB`.
