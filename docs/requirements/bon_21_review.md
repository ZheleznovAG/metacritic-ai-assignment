# BON-21: мониторинг фактической обработки

Дата: 2026-09-16. Связи: `OPS-01`, `AC-OPS-01/02`, `ASM-B03`,
`R-BON-OPS-01`; сохранение `RUN-01`, дневного лимита и `NFR-03`.
Текущий статус и зависимости — только в [action_plan.md](../../action_plan.md).

## Реализация и независимые проверки

| Критерий | Реализация | Проверка |
|---|---|---|
| Реальное состояние, а не клиентская имитация | [Snapshot](../../app/processing/monitoring.py): PostgreSQL REPEATABLE READ / READ ONLY, history <=20, allowlist | [PostgreSQL tests](../../app/tests/test_monitoring.py): конкурентный commit между запросами не создаёт смешанный snapshot; запись в read-only транзакции запрещена |
| Живые и финальные счётчики совпадают | [Run progress](../../app/processing/progress.py), frozen batch membership, один outcome на candidate, отдельные attempts | Заблокированный fake HTTP оставляет run незавершённым: UI/API уже видит 1 успешный из 3; после crash та же партия 20 заканчивается 19/1 при 21 attempt |
| Статусы процессов при долгом HTTP/потере связи | [Heartbeat](../../app/processing/heartbeat.py), отдельная thread-local DB connection; generation fence, progress deadline | [Heartbeat tests](../../app/tests/test_process_heartbeat.py): blocked main thread, stale/overdue/stop/restart, поздний старый instance, feature off |
| Изменение не позднее 5 с, refresh/reconnect | [UI](../../app/presentation/static/presentation/monitoring.js): polling 1 с, timeout/backoff 2 с, stale после 5 с, monotonic local timer | [Chromium tests](../../app/tests/test_monitoring_e2e.py): каждый committed state, outage/reconnect без online event, старый ответ, refresh/keyboard, mobile/no-JS |
| Ограниченный snapshot и нагрузка | Fixed query count, никакого внешнего HTTP в GET | [Load test](../../app/tests/test_monitoring_load.py): 10 observers, 10 000 runs, 100 000 jobs; 30 snapshots <=1 с, <=64 KiB; каталог доступен параллельно; сохраняется EXPLAIN |
| Upgrade не теряет историю | Additive [migration](../../app/processing/migrations/0003_monitoring_progress.py) | Реальное downgrade/upgrade schema на disposable DB сохраняет attempts/FKs; отсутствующий legacy batch не реконструируется |
| Изоляция и честные ошибки | Web SELECT-only, no mutating endpoint, feature flag | POST 405, disabled 404, DB outage generic 503, sanitised error-code allowlist; обычные permission/security tests сохраняются |

## Adversarial self-review

Проверены требования, AC, риски, отказные сценарии и missing evidence. Отдельные
агенты не запускались. Существенные исправления в ходе review:

- Счётчики только из terminal ProcessingRun скрывали прогресс: active snapshot
  считает committed CoreAttempt, финал использует тот же per-candidate oracle.
- Resume мог выбрать новую партию и потерять смысл selected: состав сохраняется
  до core HTTP, нормальные failed не повторяются внутри той же партии, interrupted
  attempt возобновляется в её прежнем бюджете.
- Поздний экземпляр одного run мог закрыть/освободить новую generation:
  terminal update и release используют исходный fencing token. Проверены и уже
  завершившийся, и ещё работающий новый owner.
- Старые runs не содержат membership: upgrade сохраняет историю, а interrupted
  legacy run закрывается с явной причиной вместо выдуманной реконструкции.
- Backoff 10 с противоречил восстановлению <=5 с без browser online event:
  ограничен 2 с; reconnect проверен именно без такого события.
- Ошибка транзакции регистрации heartbeat оставляла локальную generation и
  препятствовала retry: generation теперь принимается только после commit;
  regression test сначала подтвердил провал `1 != 0`, затем прошёл с исправлением.
- Playwright sync API использует event loop: тестовые ORM commits вынесены
  в отдельное соединение/поток; Django async-safety не отключена.

## Evidence и границы

Полный локальный suite прошёл: 355 application tests до последней regression-проверки
heartbeat; после исправления все 4 heartbeat tests прошли повторно. Финальный Linux
suite в Docker прошёл с **356 application tests**, проверками ролей БД, Ruff/mypy,
миграций, static и исследовательских oracle. [Команды и execution excerpts](../evidence/bon-21-local-verification.txt).

[Browser timing](../evidence/bon-21-browser-timing.json) фиксирует committed state → DOM
и reconnect <=5 с. [Нагрузочный отчёт](../evidence/bon-21-load.json): 10 наблюдателей,
10 000 runs / 100 000 jobs, 30 snapshots; max 0,218 с, application CPU 0,625 с за
3,047 с, SQL plan приложен. Это Windows/disposable PostgreSQL измерение, не SLA
публичного хоста. [Desktop](../evidence/bon-21-monitoring-desktop.png) и
[mobile](../evidence/bon-21-monitoring-mobile.png) сняты настоящим Chromium на fixtures.

Hosted CI, публичные heartbeat/counters, ресурсы и deployment identity остаются
необходимым evidence перед окончательной приёмкой; локальный suite их не заменяет.

Candidate source: `0b41b9fd8cacaa4e3172b8465e2afe3355835396`. Локальный runtime
собран; `scripts/verify_image.py` подтвердил image ID/version. [Release manifest](../evidence/bon-21-release.json)
содержит digest образа и архивов. Конфигурационный архив не содержит `.env` или secrets.
2026-09-16 после отказа automatic approval review владелец явно разрешил push
и update сервиса после успешного CI. Первый [CI run 35084338338](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/35084338338)
на `64623f7` подтвердил 356 application tests, затем выявил недопустимую запись
`Blocked / Ask` в колонке статуса. Трекер исправлен на штатный `In progress`;
код приложения не менялся. Обновление сервиса ожидает полного successful CI.

Второй [CI run 35084784807](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/35084784807)
прошёл весь offline suite, затем обнаружил прежний конфликт runtime smoke с
добавленными в app profile scheduler/worker: Compose `--wait` отвергает намеренно
отключённый HTTP healthcheck фонового процесса. Runtime smoke теперь явно поднимает
`web caddy` и их зависимости; background processing проверяется normal suite с
controlled inputs. Это также исключает запуск live ingestion в deterministic CI.

Проект `BON-22` остаётся отдельной задачей. Этот срез не добавляет операторов,
sessions или команд запуска и не меняет права web на продуктовые данные.
