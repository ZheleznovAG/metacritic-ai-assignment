# Runbook: экспорт, локальный запуск и перенос сервиса

Пошаговая ручная процедура: снять состояние с VDS, поднять сервис локально, при необходимости развернуть на новом хосте и корректно отключить старый VDS. Команды из разделов 1, 2 и 5 выполнены и проверены 2026-09-20 на релизе `7fd4e09cb43474607fdfc82cbaba5932df3299c5` (боевой VDS Amsterdam, Ubuntu 24.04, 2 vCPU / 4 ГБ). Раздел 4 (новый хост) собран из `deploy/README.md` и не повторялся. Раздел 6 (туннель) — проект, не проверенный на практике.

Общий принцип: **код и образ воспроизводимы, состояние — нет.** Состояние — это только то, что перечислено в разделе 0. Остальное пересобирается из репозитория.

Команды даны для POSIX shell (Linux, macOS, Git Bash, WSL). Для PowerShell отличия отмечены явно. Ничего из этого документа не печатает секреты.

## 0. Что считается состоянием

| Что | Где на VDS | Заменимо? |
|---|---|---|
| База PostgreSQL (игры, отзывы, резюме, прогоны, оператор `auth_user`) | том `metacritic-imp01-prod_postgres_data` | **Нет** — снимать `pg_dump` |
| `.env.app` (пароли ролей БД, `DJANGO_SECRET_KEY`) | `~/metacritic-ai-assignment-imp01/.env.app` | Можно сгенерировать заново (`init_env.py`), но тогда нужно пересоздать роли БД и сессии станут недействительны |
| `.env.worker` (`GROQ_API_KEY`) | там же | Ключ можно перевыпустить в консоли Groq |
| Сертификаты Let's Encrypt | том `..._caddy_data` | Да — Caddy выпустит заново для нового hostname |
| Docker-образ | tar в каталоге проекта | Да — собирается из коммита (раздел 3) |
| Бэкапы `backups/before-*` | каталог проекта | Копии БД на моменты обновлений, для отката |

Данные на 2026-09-20: БД 49 МБ (дамп 7.4 МБ), 771 игра, 15 362 отзыва, 1 608 резюме, 112 прогонов, 1 оператор. Пик памяти всех контейнеров ≈ 680 МБ.

## 1. Экспорт с боевого сервера (только чтение)

Значения берутся из операторского `.env`: `DEPLOY_SSH_HOST`, `DEPLOY_SSH_PORT`, `DEPLOY_SSH_USER`, `DEPLOY_SSH_KEY_PATH`. Каталог экспорта лежит в `.artifacts/`, который игнорируется git: **никогда не коммитить**, внутри пароли и ключи.

```sh
H=deploy@<DEPLOY_SSH_HOST>; KEY=<DEPLOY_SSH_KEY_PATH>
D=.artifacts/vds-export-$(date +%F); mkdir -p "$D"; chmod 700 "$D"
S="ssh -i $KEY -o BatchMode=yes $H"
P=metacritic-imp01-prod          # имя Compose-проекта на VDS
DIR=metacritic-ai-assignment-imp01

# 1. Логический дамп БД (consistent snapshot, сервис можно не останавливать)
$S "docker exec ${P}-db-1 sh -c 'pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Fc'" > "$D/database.dump"

# 2. Контрольные счётчики строк, чтобы сверить после восстановления
$S "docker exec ${P}-db-1 psql -U metacritic -d metacritic -Atc \
  'select relname, n_live_tup from pg_stat_user_tables order by 1'" > "$D/table-counts.txt"

# 3. Конфигурация и секреты (.env.app, .env.worker, compose, Caddyfile)
$S "cd ~/$DIR && tar czf - .env.app .env.worker compose.yaml compose.production.yaml deploy" \
  > "$D/server-config-and-secrets.tar.gz"

# 4. Образ текущего релиза (имя tar = версия; смотреть APP_VERSION в .env.app)
scp -i "$KEY" $H:$DIR/image-<APP_VERSION>.tar "$D/"

# 5. Контрольные суммы + проверка читаемости дампа
( cd "$D" && sha256sum * > SHA256SUMS && sha256sum -c SHA256SUMS )
pg_restore --list "$D/database.dump" | wc -l    # если pg_restore установлен; иначе см. раздел 2, шаг 4
```

Признак успеха: `pg_restore --list` выдаёт ~380 строк, `SHA256SUMS` сходится. Экспорт 2026-09-20: `.artifacts/vds-export-2026-09-20/`.

Копию каталога экспорта храните вне ноутбука (зашифрованный облачный диск или внешний носитель): это единственная копия состояния после удаления VDS.

Если tar образа на VDS нет, образ всё равно можно снять с запущенного сервера: `$S "docker save metacritic-imp01:<APP_VERSION>" > "$D/image-<APP_VERSION>.tar"`.

## 2. Локальный запуск из экспорта

Проверено: Docker Engine 29 + Compose 5.4 на Windows. Каталог запуска повторяет раскладку сервера, поэтому не трогает рабочий `.env.app` в корне репозитория и другие локальные проекты. Имя проекта `metacritic-local` не пересекается с существующими.

```sh
E=.artifacts/vds-export-<дата>; L=.artifacts/local-run
V=<APP_VERSION>                  # напр. 7fd4e09cb43474607fdfc82cbaba5932df3299c5

# 1. Раскладка (то же, что переносится на VDS архивом конфигурации)
mkdir -p $L/scripts $L/deploy
cp compose.yaml compose.production.yaml .env.app.example .env.worker.example $L/
cp deploy/Caddyfile deploy/Caddyfile.production deploy/Caddyfile.snippets $L/deploy/
cp scripts/init_env.py scripts/verify_image.py scripts/smoke.py \
   scripts/grant_manual_run_access.py scripts/provision_db.py $L/scripts/
docker load -i $E/image-$V.tar

# 2. Окружение. Варианты:
#    a) свежее: новые пароли (БД восстанавливается из дампа, пароли ролей задаёт db_setup — они не обязаны совпадать с VDS)
cd $L && python scripts/init_env.py --version $V
cat >> .env.app <<EOF
APP_IMAGE=metacritic-imp01:$V
COMPOSE_PROJECT_NAME=metacritic-local
EOF
sed -i "s/^APP_VERSION=.*/APP_VERSION=$V/" .env.app
#    б) точная копия боевого: распаковать server-config-and-secrets.tar.gz и поправить только
#       POSTGRES_HOST/PORT, APP_HTTP_BIND, DJANGO_ALLOWED_HOSTS, DJANGO_HTTPS=false, убрать CADDYFILE_NAME

C="docker compose -p metacritic-local --env-file .env.app"
$C --profile app config --quiet && echo CONFIG_OK

# 3. Поднять только БД и создать роли (db_setup). Web/scheduler/worker пока НЕ запускать —
#    иначе scheduler начнёт наполнять пустую базу живыми данными раньше восстановления.
$C up -d --wait db
$C --profile app run --rm db_setup

# 4. Восстановить данные в пустую БД (суперпользователь POSTGRES_USER, владельцы объектов сохраняются)
docker exec -i metacritic-local-db-1 sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error --single-transaction' < ../vds-export-<дата>/database.dump
#    PowerShell (нет оператора <): docker cp ..\vds-export-<дата>\database.dump metacritic-local-db-1:/tmp/database.dump
#      docker exec metacritic-local-db-1 sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error --single-transaction /tmp/database.dump; rm /tmp/database.dump'

# 5. Сверка: должно совпасть с table-counts.txt (771 игра, 15362 отзыва, 34 миграции)
docker exec metacritic-local-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "select count(*) from catalog_game; select count(*) from reviews_review; select count(*) from django_migrations"'

# 6. Приложение. up сам повторит db_setup → migrate → db_grants (права web на запись), затем web и caddy.
$C --profile app up -d web caddy            # без scheduler/worker, если нужна «замороженная» копия
$C --profile app up -d                      # всё, включая scheduler и worker
$C --profile app ps -a
python scripts/smoke.py http://127.0.0.1:18081 --version $V     # все PASS
```

Поведение, подтверждённое при репетиции:
- `db_setup` → `pg_restore` → `up` работает: `migrate` ничего не меняет (34/34 уже применены), `db_grants` возвращает web его точечные права на запись.
- После `up scheduler` первый запуск сразу распознал восстановленное состояние: `run_id=112 … outcome=skipped_duplicate` для слота 06:00 (та же идемпотентность, что и на боевом).
- Без `.env.worker` worker пишет `idle: … (GROQ_API_KEY not set, skipping summary work)`: сбор отзывов идёт, резюме не генерируются. Сделать `.env.worker` из `.env.worker.example`, права `0600`, проставить ключ, затем `$C --profile app up -d worker`. **Groq строго в рамках бесплатных лимитов**, платный тариф без согласования не включать.
- Оператор (`auth_user`) переезжает вместе с дампом: вход по прежнему паролю. Новый оператор: `$C --profile app run --rm --no-deps migrate python app/manage.py create_operator <имя>`.
- Порт БД на хосте `127.0.0.1:${POSTGRES_PORT:-15432}`, web через Caddy `127.0.0.1:${APP_HTTP_PORT:-18081}`. При конфликте поменять в `.env.app`.
- Память локально: web ≈ 120 МБ, db ≈ 90 МБ, caddy ≈ 13 МБ.

Остановка и удаление локальной копии:

```sh
$C --profile app down          # остановить, данные сохраняются в томе
$C --profile app down -v       # остановить и УДАЛИТЬ тома metacritic-local_* (только для этого проекта)
```

Никогда не выполнять `down -v`, `docker volume prune` и `docker system prune --volumes` в проекте, данные которого нужны.

## 3. Сборка образа из исходников (если tar потерян)

```sh
git checkout <commit-релиза>          # напр. 7fd4e09cb43474607fdfc82cbaba5932df3299c5
docker build --target runtime --build-arg APP_VERSION=<commit> -t metacritic-imp01:<commit> .
docker image inspect metacritic-imp01:<commit> --format '{{.Id}}'    # записать sha256
docker save --output image-<commit>.tar metacritic-imp01:<commit>
```

Версия зашита в образ и не зависит от рантайм-`APP_VERSION`. Повторная сборка не гарантирует тот же image ID, поэтому после неё запускайте `verify_image.py --image ... --version <commit>` (проверяет версию и, если указан, `--image-id`). Актуальный код (HEAD) новее развёрнутого релиза: при переносе решите, ставить проверенный `7fd4e09` или новый.

## 4. Развёртывание на новом хосте (VDS)

Полное описание — [`deploy/README.md`](README.md); ниже порядок и ловушки.

1. Хост: Ubuntu 24.04, Docker Engine + Compose ≥ 2.24.4 (на боевом 2.40), пользователь `deploy` в группе `docker`, вход по ключу. Открыть только 22, 80, 443. Для нагрузки достаточно **1 vCPU / 2 ГБ** (1 ГБ — только с swap и `--workers 1`).
2. `umask 077; mkdir ~/metacritic-ai-assignment-imp01` (порт 18081 должен быть свободен), перенести архив конфигурации (список файлов — `deploy/README.md`, шаг 2) и tar образа, сверить SHA-256, `docker load -i`.
3. Секреты: распаковать `server-config-and-secrets.tar.gz` из экспорта (там уже `.env.app` и `.env.worker`) **или** `python3 scripts/init_env.py --production --host <hostname> --version <V>` и создать `.env.worker` (`chmod 0600`, `GROQ_API_KEY`).
4. Порядок такой же, как в разделе 2: `up -d --wait db` → `--profile app run --rm db_setup` → `pg_restore` → `up -d` (проект `metacritic-imp01-prod`, файлы `compose.yaml` + `compose.production.yaml`). Не использовать `--wait` для `up` всего профиля app (Compose 2.40 отказывает на сервисах с отключённым healthcheck). Все `run --rm migrate|db_setup` после первого деплоя только с `--no-deps`; иначе `db_setup` обнулит права web (лечится `run --rm --no-deps db_grants`).
5. TLS: hostname должен уже указывать на IP нового хоста (`nslookup`), в `.env.app` добавить его в `DJANGO_ALLOWED_HOSTS`, поставить `DJANGO_HTTPS=true`, `CADDYFILE_NAME=Caddyfile.production`, в `deploy/Caddyfile.production` заменить адрес сайта (сейчас `v978670.hosted-by-vdsina.com`, он исчезнет вместе с VDS). Порт 80 нужен для HTTP-01. Проверка: `curl https://<hostname>/` без `-k`, `python3 scripts/smoke.py https://<hostname> --version <V>` с самого хоста и с внешней машины.
6. Бэкап по расписанию (на VDS его сейчас нет — только перед обновлениями): `cron` раз в сутки — `pg_dump -Fc` в `backups/`, хранить последние 7 штук, копию раз в неделю выносить с хоста.

## 5. Отключение старого VDS

Выполнять только после того, как новая копия (локальная или на другом хосте) прошла smoke и сверку счётчиков.

1. **Финальный дамп**: повторить раздел 1 (можно остановить `scheduler`/`worker` перед дампом, чтобы после него не появилось новых данных: `docker compose -p metacritic-imp01-prod --env-file .env.app -f compose.yaml -f compose.production.yaml stop scheduler worker`).
2. Сверить `SHA256SUMS`, сделать вторую копию экспорта вне ноутбука.
3. Убедиться, что восстановленная копия читает те же счётчики (`table-counts.txt`).
4. Остановить сервис: `... --profile app down` (без `-v`), затем удалить VDS в панели поставщика. После удаления прежний IP-адрес (`DEPLOY_SSH_HOST` из операторского `.env`) и hostname `v978670.hosted-by-vdsina.com` перестают быть вашими: любые ссылки на них в резюме/README/отчётах станут мёртвыми.
5. Вывести из обращения: SSH-ключ `metacritic_deploy` (удалить файл и запись в `authorized_keys` на других хостах), строки `DEPLOY_SSH_*` в `.env` (или всю переменную), при необходимости перевыпустить `GROQ_API_KEY`, если секреты лежали только на VDS.
6. Репозиторий: hostname и IP упоминаются в `deploy/Caddyfile.production`, `deploy/README.md`, `docs/evidence/*`, `docs/requirements/*`, `action_plan.md`. Это исторические доказательства для отправленного задания: **не переписывать**, а зафиксировать в `action_plan.md` отдельной записью, что публичный экземпляр отключён (дата, причина).

## 6. Вариант: дешёвый VDS как публичный вход, сервис на домашнем ноутбуке

Проект. Не проверялся на практике; перед использованием отрепетировать.

```
Интернет → VDS (Caddy, TLS 80/443) ──WireGuard──► ноутбук (compose: db, web, scheduler, worker)
```

- Ноутбук сам поднимает туннель к VDS (исходящее соединение, роутер настраивать не нужно), `PersistentKeepalive = 25`. Адреса туннеля, например, VDS `10.8.0.1`, ноутбук `10.8.0.2`.
- На VDS остаётся только Caddy: сайт `<hostname> { reverse_proxy 10.8.0.2:18081 }`. Тариф 1 core / 1 ГБ достаточно. Наружу открыть 80/443 и UDP-порт WireGuard, доступ к `10.8.0.2` ограничить портом 18081.
- На ноутбуке `APP_HTTP_BIND=10.8.0.2` (или `0.0.0.0` за файрволом), порт БД наружу не публиковать.
- **IP клиента.** Web увидит адрес VDS. Перед запуском проверить, что Caddy передаёт `X-Forwarded-For`/`X-Forwarded-Proto`, а Django и лимиты для `/ops/run/` и логина их учитывают, иначе ломаются HTTPS-редирект и rate limiting.
- Ноутбук: отключить сон/гибернацию (в том числе при закрытии крышки), автозапуск Docker и WireGuard, восстановление после сбоя питания. Рекомендуется Linux; в Docker Desktop/WSL2 автозапуск менее предсказуем.
- Если ноутбук офлайн, сайт недоступен, почасовые окна пропускаются; `RunCandidate` и восстановление переживают перерыв. На VDS настроить Caddy `handle_errors` со страницей 503.
- Ежедневный `pg_dump` с ноутбука на VDS (`scp`) — единственная копия вне дома.
- Тариф текущего VDS нельзя понизить (ограничение поставщика): для 1 core / 1–2 ГБ нужен новый VDS, а значит, новые IP и hostname (раздел 4, шаг 5).

## Контрольный чек-лист «ничего не потеряно»

- [ ] `database.dump` читается (`pg_restore --list`), сверка счётчиков после `pg_restore` совпала.
- [ ] `SHA256SUMS` совпадает, есть копия вне ноутбука.
- [ ] `.env.app` и `.env.worker` сохранены (или готовы к перевыпуску).
- [ ] Локальный `smoke.py` — все PASS.
- [ ] Только после этого удалять VDS.
