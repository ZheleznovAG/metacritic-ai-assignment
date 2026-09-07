# ADR-0001: Минимальный стек и архитектурный контур

- **Статус:** Accepted
- **Дата:** 2026-09-07
- **Задача:** `PLN-01`
- **Связи:** все Must; `R-AI-02`, `R-DEP-01`, `R-ID-01`, `R-TIM-01–R-TIM-02`, `R-OPS-01`, `R-REP-01`

## Контекст

Сервис должен раз в час получать до 20 игр, безопасно обновлять накопленное состояние, отдельно и асинхронно обогащать отзывы через бесплатный Groq API и показывать публичный read-only web UI. Подтверждённая среда — одна VDS Ubuntu 24.04 с 2 CPU, 4 GB RAM, 80 GB persistent storage, `systemd` и публичным ingress. Docker Engine на VDS пока не проверен. Денежный бюджет не задан; новые платные зависимости запрещены.

Критические ограничения `G2`: повтор и пересечение запусков не должны дублировать работу; AI-квота требует persistent queue/cache; внешний HTML и AI должны быть заменяемыми адаптерами; production нужны UTC, supervision, TLS, диагностируемые run records и воспроизводимые offline tests. Комплект сдачи также должен воспроизводиться без совпадения незафиксированных host packages.

## Решение

Выбран контейнеризованный модульный монолит: один репозиторий, один immutable Python application image с внутренними модулями и общими доменными правилами, одна PostgreSQL-база и три application entry points. На единственной production VDS весь контур управляется Docker Compose; orchestration cluster не нужен.

```text
Docker Compose on Ubuntu VDS

Internet -> Caddy -> web (Gunicorn/Django) ----+
Metacritic <- scheduler (same application image) +--> PostgreSQL -> named volume
Groq <------ worker (same application image) ----+       |
                                                        +--> run/job records
All containers -> bounded structured stdout/stderr logs
```

### Стек

| Слой | Выбор | Потребность / основание |
|---|---|---|
| Runtime | Python 3.12 в version/digest-pinned application image | Один immutable runtime для production web/scheduler/worker и CI. Локальный Python 3.14 допустим как дополнительная проверка, но canonical runtime — 3.12. |
| Application | Django 5.2 LTS, WSGI | ORM, migrations, server-rendered UI, management commands и test client в одном framework; LTS поддерживает Python 3.12. Закрывает `DATA-*`, `UI-*`, `SIM-*`, `NFR-04`, `NFR-06` без отдельного API/SPA-контура. |
| Persistence | PostgreSQL 16 container + Psycopg 3 + named data volume | Транзакции, constraints, row/advisory locks и `SKIP LOCKED` дают проверяемую основу identity, lease, idempotency и DB-backed queue для `DATA-01`, `NFR-01–NFR-03`; данные живут вне lifecycle контейнера. |
| External HTTP | HTTPX; Beautiful Soup 4 поверх стандартного `html.parser`; стандартный `json` для SSR payload | Один timeout/retry-aware client и простой HTML/JSON adapter для подтверждённого server-rendered Metacritic contract; JavaScript browser не нужен. |
| AI | Тонкий Groq Chat Completions adapter через HTTPX; модель и prompt version задаются конфигурацией | Сохраняет прошедший `SPK-05` контракт `openai/gpt-oss-20b`, strict JSON Schema, source language и no-paid-fallback; provider не проникает в domain/UI. |
| UI | Django templates, обычные CSS и минимальный progressive JavaScript | `UI-01–UI-05` не требуют SPA. Поиск, фильтр, сортировка и навигация остаются server-side и доступны по обычным URL. |
| Configuration | Стандартные environment variables; `python-dotenv` локально и ignored permission-restricted `.env`/`env_file` в Compose | Выполняет выбранный владельцем workflow; Groq key не попадает в web/Caddy, Git, image или logs. Публиковать вывод `docker compose config` запрещено. |
| Web runtime | Gunicorn WSGI + WhiteNoise за Caddy container | Низкая сложность для read-mostly UI; Caddy завершает TLS и проксирует только в internal Compose network, WhiteNoise отдаёт versioned static assets без общего writable mount. |
| Scheduling / supervision | Отдельный UTC scheduler container из application image; Compose restart policies и healthchecks | Scheduler регистрирует unique hourly slot в PostgreSQL и безопасно восстанавливается после restart; DB остаётся источником истины. Cron и process manager внутри контейнера не нужны. |
| Observability | Persistent run/job records в PostgreSQL + структурированные container logs с rotation limits | Даёт время, outcome, counters и correlation IDs для `NFR-05`; отдельный monitoring stack для Must не нужен, а logs не заполняют диск без границы. |
| Verification | Django/unittest test stack, fakes/fixtures; Python Playwright только для обязательного Chromium E2E | Обычный CI не обращается к live Metacritic/Groq; browser dependency добавляется только для `AC-UI-*`/`IMP-07`, live checks остаются отдельными. |
| Packaging / deployment | `pyproject.toml`, exact resolved dependency lock, multi-stage Dockerfile и `compose.yaml` + production override | Локально Python/test commands выполняются прямо в `.venv`, а Compose даёт PostgreSQL; production запускает versioned application image без bind mount исходников. Точный lock и manifests создаются в `IMP-01`. |

В production все timestamps и календарные решения используют UTC независимо от системной зоны VDS. Секреты передаются через ignored `.env` с правами только владельцу deploy и scoped service environment; они не входят в Git, image, frontend или logs.

### Границы процессов

- Web container выполняет только read-only presentation queries и health/readiness checks; он не запускает ingestion или AI по HTTP в Must-контуре.
- Scheduler container ожидает границу UTC-часа, атомарно регистрирует slot/run, получает единственное владение дневной партией, сохраняет валидные игровые данные и ставит изменившиеся audience inputs в persistent AI queue. После restart он сверяется с DB, а не с памятью процесса.
- AI worker независимо забирает ограниченное число jobs, применяет fingerprint/cache, bounded retry/backoff и сохраняет только канонически валидный результат либо диагностируемое состояние ошибки/задержки.
- PostgreSQL — единственный источник истины для game identity, progress, leases, AI jobs и run records. Container logs — диагностический вывод, а не состояние процесса.

Точные таблицы, транзакционные границы, состояния и Python interfaces относятся к `PLN-02`; этот ADR фиксирует только компоненты и ответственность.

## Рассмотренные альтернативы

| Альтернатива | Решение |
|---|---|
| FastAPI + SQLAlchemy + Alembic + Jinja | Отклонена: даёт хороший API-first контур, но здесь потребует собирать отдельно ORM, migrations, forms/templates и testing glue без требования внешнего API. |
| SQLite | Отклонена для production: проще bootstrap, но одновременные web/ingest/AI processes и queue ownership делают write-locking и parity дополнительным риском. PostgreSQL уже доступен как штатный Ubuntu package. |
| Celery + Redis | Отклонена: persistent retry queue нужна, но ожидаемая нагрузка мала; дополнительный broker, worker protocol и отдельное состояние не дают обязательной ценности. |
| React/Vue SPA и JSON API | Отклонены: публичный read-only UI не требует rich client; отдельная сборка, API contract и hydration увеличат delivery/E2E surface. |
| Native Python/PostgreSQL/Caddy + systemd application units на VDS | Отклонена: runtime работоспособен, но host package drift, больше privileged provisioning и отличающийся local/production setup ухудшают главный delivery artifact. Docker Compose официально пригоден для single-server production и фиксирует весь контур. |
| Nginx + Certbot | Отклонена в пользу Caddy: оба пригодны, но Caddy объединяет reverse proxy, получение/renewal сертификата и HTTP→HTTPS в одном малом config. |
| Host cron/systemd timer либо cron внутри container | Отклонены: создают второй orchestration contract или смешивают процессы. Отдельный scheduler container использует те же domain rules и восстанавливает hourly slots из PostgreSQL. |

## Последствия и ограничения

- На VDS будут пять Compose services: `caddy`, `web`, `scheduler`, `worker`, `db`; последние три используют один application image. Redis, Node runtime, vector DB, Kubernetes и отдельные микросервисы не нужны.
- PostgreSQL требует integration/concurrency tests на том же backend; SQLite не используется как скрытая замена в CI.
- Локальный preflight подтвердил Docker Engine 29.7.2 (`linux/amd64`) и Compose 5.4.0; `psql`/`pg_config` на Windows отсутствуют. Python application и test commands остаются в локальном `.venv`; Compose запускает локальную БД и весь production contour.
- AI backlog может расти при исчерпании Groq Free TPD, но не блокирует сохранение основных данных и не включает платный fallback.
- Production preflight ещё должен подтвердить Docker Engine + Compose plugin и право deploy-user управлять daemon. Если этого нет при старте раннего deploy `IMP-01`, задача помечается `Blocked / Ask`, `needed-by: G4`; обход через rootless ad-hoc processes не принимается.
- Caddy с публично доверенным TLS требует hostname, DNS на VDS и внешние порты 80/443. Если они не предоставлены к `PUB-01`, задача помечается `Blocked / Ask`, `needed-by: G6`.
- PostgreSQL и Caddy state размещаются в явно именованных volumes; release/recreate не удаляет их. Команды с удалением volumes не входят в обычный deploy, а backup/restore должен быть проверен до release.
- До `G6` обязательны host-reboot check, две последовательные application schedule windows и внешний HTTPS smoke. До них выбранная схема является решением, а не доказанным production deployment.
- Compose не гарантирует capacity: initial cardinality ограничена двумя sync Gunicorn workers, одним scheduler и AI concurrency `1`; memory/CPU/healthchecks измеряются на 4 GB VDS в `IMP-01/PUB-01`. При давлении сначала уменьшаются concurrency и batch; новый broker/service добавляется только после evidence.

## Источники решения

- [Django 5.2 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2/) — LTS и совместимость Python.
- [Django database support](https://docs.djangoproject.com/en/5.2/ref/databases/) — PostgreSQL/Psycopg и UTC connection behavior.
- [PostgreSQL 16 locking clauses](https://www.postgresql.org/docs/16/sql-select.html) и [advisory locks](https://www.postgresql.org/docs/16/functions-admin.html) — queue/ownership primitives.
- [Official PostgreSQL 16 container image](https://hub.docker.com/_/postgres) — versioned image и persistent data path.
- [Django with Gunicorn](https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/gunicorn/) — минимальный WSGI deployment.
- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https) и [Docker Compose guidance](https://caddyserver.com/docs/running#docker-compose) — TLS и container deployment contract.
- [Docker Compose in production](https://docs.docker.com/compose/how-tos/production/) — single-server deployment и production override.
- [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/) и [volumes](https://docs.docker.com/engine/storage/volumes/) — restart и persistent state вне container lifecycle.
- [Compose environment files](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/) — scoped configuration через `env_file`.
