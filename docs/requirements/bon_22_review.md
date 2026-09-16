# BON-22: защищённый принудительный запуск

Дата: 2026-09-17. Связи: `OPS-02`, `AC-OPS-03`, `ASM-B04`, `R-BON-OPS-02`; сохраняет
`AC-OPS-01/02`, дневной лимит 20, review handoff и Groq quota. Контракт —
[Candidate](../bonus2_design.md). Текущий статус и зависимости — только в
[action_plan.md](../../action_plan.md).

## Реализация и независимые проверки

| Критерий | Реализация | Проверка |
|---|---|---|
| Auth/DB sessions, отсутствие registration/admin UI | Стандартные `django.contrib.auth`/`sessions`; `processing.management.commands.create_operator` создаёт не-superuser аккаунт с одним permission (`processing.trigger_run`), пароль не логируется/не попадает в evidence | [test_operators_views.py](../../app/tests/test_operators_views.py): login/logout, generic errors, inactive account, GET/POST границы |
| CSRF, login throttling, session expiry | `@csrf_protect` + кастомный `CSRF_FAILURE_VIEW` (JSON 403 везде); `LoginFailure` — 5 неуспешных попыток / 15 минут на username и отдельно на client IP (из `X-Forwarded-For`, последний hop — только Caddy может достичь web); `SESSION_COOKIE_AGE=8h` | `test_operators_views.py`: throttled 6-я попытка не проходит даже с верным паролем и не создаёт новых строк; `test_csrf_failure_is_json_403` |
| Явная allowlist вместо blanket grants | [scripts/grant_manual_run_access.py](../../scripts/grant_manual_run_access.py) — отдельный шаг **после** `migrate` (в отличие от `provision_db.py`, который создаёт роли **до** него): по имени называет ровно 5 таблиц/колонку (`django_session` полностью, `auth_user.last_login` только эта колонка, `processing_manualrunrequest` только `INSERT`, `processing_triggeradmission` только `UPDATE`, `processing_loginfailure` только `INSERT`); ничего не расширяет существующий blanket read-only grant web. Compose: новый `db_grants` сервис между `migrate` и `web` | [scripts/tests/test_database_roles_manual_run.py](../../scripts/tests/test_database_roles_manual_run.py): реальный PostgreSQL, throw-away таблицы с реальными именами, подтверждён каждый allow и каждый deny (web не может update/delete `processing_manualrunrequest`, не может insert в `processing_triggeradmission`, не может менять другие колонки `auth_user`) |
| Durable manual request, idempotency key, cooldown/rate-limit, audit | [processing/admission.py](../../app/processing/admission.py): `TriggerAdmission` singleton-lock (тот же идиом, что `ProcessingLease`); идемпотентность проверяется первой (replay не тратит квоту); busy — advisory read лизы (web никогда не делает `SELECT FOR UPDATE` на `ProcessingLease`); rate limit — 1 новый запрос/5 мин + 6/час, реальный конкурентный тест | [test_admission.py](../../app/tests/test_admission.py) (12 тестов) + [test_manual_run_concurrency.py](../../app/tests/test_manual_run_concurrency.py): два реальных потока на один и тот же key/на последний часовой слот — ровно один victor |
| Общий admission/execution, scheduler без ожидания часа | [processing/scheduler.py`run_manual`](../../app/processing/scheduler.py) переиспользует `_try_resume`/`_execute_and_close`/`TickResult` из `run_tick`, не параллельная реализация; [processing/dispatcher.py](../../app/processing/dispatcher.py) — отдельный поток с собственным DB-соединением и собственным `Heartbeat(slot="manual-dispatcher")`, опрашивает очередь раз в секунду; hourly `run_tick` не меняется | [test_manual_run.py](../../app/tests/test_manual_run.py) (7 тестов): claim→execute→complete, conflict когда lease уже занят, resume после "crash" между claim и исполнением, живой другой владелец оставляет `claimed` для следующего тика |
| Run processing и результаты queued/busy/rate-limited/invalid/forbidden | [presentation/operators.py](../../app/presentation/operators.py)`run_view`: anonymous/no-permission/CSRF — всегда JSON 403 без постановки в очередь; invalid UUID/чужой ключ — 400 без раскрытия; busy — 409 со ссылкой на run; rate-limited — 429 + `Retry-After`; успех — 202/200 (JSON) или redirect на `/ops/?request=` (обычная форма, работает без JS) | `test_operators_views.py::RunViewTests` (10 тестов на каждую ветку) |
| Авторизация проверяется на каждый POST, а не скрытием кнопки | Кнопка рендерится только при `can_trigger_run`, но `run_view` независимо проверяет `has_perm` при каждом запросе | `test_authenticated_without_permission_is_rejected_with_json_403` — прямой POST в обход UI |
| Реальные конкурентные DB-соединения | `tests.concurrency.run_concurrently` (тот же harness, что HRD-03) — два потока на тот же idempotency key, на последний часовой rate-limit слот, на тот же `ManualRunRequest.pk` (два "dispatcher") | Все три сценария: ровно один victor, `gateway.calls == 1` для dispatcher-гонки |
| Публичный/анонимный observer не видит audit | `/ops/status/` не тронут (кроме честного `trigger_kind` в истории runs); отдельный `run_status_view` требует аутентификации и возвращает только запросы **своего** оператора (404 на чужой) | `test_another_operators_request_is_not_found` |
| Браузерный E2E | [test_operators_e2e.py](../../app/tests/test_operators_e2e.py): anonymous → wrong password → permission-less account → permitted operator → реальный admitted POST → симулированный dispatcher claim (тот же паттерн, что `test_monitoring_e2e.py` использует для scheduler/worker) → live-polling статус до "finished" | Chromium, реальные HTTP/DB, без моков UI |

## Adversarial self-review

Реальное test-driven обнаружение (не отдельный агент-проход; каждая находка
подтверждена падением до исправления):

- **`run_manual` путал "первая попытка" с "resume".** Изначальная версия единообразно
  вызывала `_try_resume` для любого не-terminal run; при проигрыше гонки лизы это
  оставляло manual request в `claimed` навсегда без наблюдаемого исхода — прямое
  нарушение design ("conflict, а не скрытый отложенный повтор"). Исправлено: `queued`
  (первая попытка/крах до захвата лизы) гонится напрямую через `acquire_lease` и при
  `LeaseOverlap` немедленно становится `skipped_overlap`/`conflict`; только genuine
  `running` (лиза уже была захвачена этим же запросом раньше) идёт через `_try_resume`
  с его "подождать следующий тик" семантикой.
- **Гонка двух потоков одного и того же manual request могла затереть чужой прогресс.**
  Проигравший `LeaseOverlap` изначально всегда писал `skipped_overlap` в `run` — включая
  случай, когда лизу выиграл **другой поток этого же request** (два dispatcher во время
  overlapping deploy). Это могло перезаписать статус ещё выполняющегося run. Исправлено:
  проверка `ProcessingLease.owner_run_id == run.pk` — если это тот же run, проигравший
  просто возвращает `None` и не трогает строку.
- **`SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` были жёстко `True`.** Безобидно, пока
  auth не использовался; реальный браузер (Playwright E2E) немедленно показал, что
  сессия никогда не сохраняется на `DJANGO_HTTPS=false` (локально/CI) — cookie с флагом
  `Secure` не отправляется по plain HTTP. Исправлено: оба флага теперь следуют
  `SECURE_SSL_REDIRECT`, как уже делают `SECURE_HSTS_*`.
- **`TEMPLATES` не регистрировал `request`/`auth` context processors.** `{% if
  request.user.is_authenticated %}` тихо резолвился в "false" всегда (Django игнорирует
  необъявленные переменные), поэтому login технически работал (сессия в БД была верна),
  но UI никогда не показывал вход. Найдено тем же E2E-тестом после исправления cookie;
  добавлены `django.template.context_processors.request` и
  `django.contrib.auth.context_processors.auth`.
- **`ManualRunRequest.created_at` был `auto_now_add=True`.** Ломало сравнение с
  инжектируемым `Clock` в `admission.py` (rate-limit/cooldown математика сравнивала
  реальные wall-clock таймстемпы с фиктивным `FakeClock`). Исправлено на явное поле,
  как уже сделано для `ProcessingRun.started_at`/`ended_at`.
- **Grant-тест использовал недоступные `POSTGRES_USER`/`POSTGRES_PASSWORD`.** `checks`
  профиль намеренно не получает admin-креды; исправлено на использование `MIGRATE_DB_USER`
  (владелец throw-away таблиц) — тот же SQL из `grant_manual_run_access.grant()`,
  реальная привилегия владельца объекта вместо суперпользователя.

## Границы и явные ограничения

- Docker/CI прогон дважды показал переходящий `statement timeout` на `flush` между
  тестами (эта же машина одновременно держит несколько других Postgres-контейнеров от
  параллельных сессий); оба раза чистый повтор с той же кодовой базой проходил
  полностью. Итоговый прогон-evidence — полностью чистый `scripts/check.py`
  (ruff/mypy/400 application tests/DB-role tests/evals) на изолированном Compose-проекте
  (`COMPOSE_PROJECT_NAME`, отдельный volume, тот же паттерн, что `.github/workflows/ci.yml`
  использует через `github.run_id`).
- Content negotiation `run_view` (JSON vs redirect) определяется по `Accept:
  application/json`; клиент без этого заголовка (например, `curl` по умолчанию) получит
  HTML-редирект, а не JSON — явный выбор для no-JS формы, не описанный дословно в
  таблице `docs/bonus2_design.md`.
- Публичный (hosted CI + VDS) прогон, upgrade/rollback repetition на реальном сервисе,
  второй анонимный observer и следующий scheduled window после manual run — отдельный
  срез этого же цикла, не входит в этот коммит.
- `docker compose ... up --wait` на VDS остаётся несовместим с отключённым healthcheck
  `scheduler`/`worker`/`db_grants` (тот же cosmetic-баг Compose 2.40.3, уже
  задокументированный в `deploy/README.md` для `BON-21`); процедура апгрейда явно не
  использует `--wait` для этого шага.

Локальный suite: **400 application tests** (44 новых для BON-22) зелёные, `ruff
format`/`check` и `mypy --strict` чистые, `makemigrations --check --dry-run` без
изменений, полный `scripts/check.py` пройден на изолированном Docker Compose проекте.

Первый push (candidate `83a171d`) нашёл ещё один реальный дефект, который ни локальный
`scripts/check.py`, ни офлайн-suite не ловят: runtime-стадия `Dockerfile` копирует из
`scripts/` только `provision_db.py` (не всю директорию, в отличие от checks-стадии) —
новый `grant_manual_run_access.py` не попадал в образ, и CI-шаг "Start the actual
runtime through Caddy" падал (`db_grants` exit 2, "can't open file"). Исправлено
добавлением аналогичной явной `COPY` строки; локально воспроизведено и подтверждено
(build+up+smoke на изолированном Compose-проекте) до пуша фикса. [Hosted CI
35131996286](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/35131996286)
на исправленном `959c2d6` прошёл полностью, включая реальный `docker compose up`
web/caddy/db_grants и внешний HTTP smoke.
