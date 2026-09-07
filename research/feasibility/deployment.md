# `SPK-06` — проверка публичной среды

## Текущий статус

**Статус:** `Blocked / Ask`, `needed-by: G2`.

**Полученный ответ владельца, 2026-09-07:** для проверки и последующего размещения доступна существующая VDS со следующими заявленными характеристиками.

| Параметр | Значение | Статус evidence |
|---|---:|---|
| ОС | Ubuntu 24.04 | Owner-provided; remote preflight pending |
| CPU | 2 cores | Owner-provided; remote preflight pending |
| RAM | 4 GB | Owner-provided; remote preflight pending |
| Storage | 80 GB | Owner-provided; free space/filesystem pending |
| Traffic | 32 TB | Owner-provided; network policy pending |
| Доступность | VDS уже доступна владельцу | Owner-provided; SSH/public reachability pending |

Hosting candidate и отсутствие необходимости выбирать новую бесплатную платформу подтверждены. Ресурсы не выглядят ограничением для минимального probe, однако площадка ещё не принята: без SSH preflight нельзя доказать persistent state, scheduler, public ingress, outbound access, secrets handling и диагностику.

## Текущий Ask

Владелец предоставит SSH host/IP, username и private key через локальную конфигурацию. Для продолжения должны быть заполнены `SPK06_SSH_HOST`, `SPK06_SSH_PORT`, `SPK06_SSH_USER` и `SPK06_SSH_KEY_PATH` в корневом `.env`.

Private key хранится отдельным файлом по `SPK06_SSH_KEY_PATH`, предпочтительно в игнорируемом каталоге `.secrets/`; в `.env` находится только путь. Содержимое ключа, `.env`, IP/username и несокращённые SSH-логи не коммитятся и не копируются в публичный evidence.

Шаблон: [`.env.example`](../../.env.example). `.env` и `.secrets/` исключены из Git корневым [`.gitignore`](../../.gitignore).

## Граница probe

Spike должен проверить способность выбранной VDS, а не преждевременно выбрать production stack. Минимальный probe использует только возможности базовой ОС либо уже установленные инструменты и создаёт изолированные ресурсы с префиксом `metacritic-ai-probe`.

Probe обязан доказать:

1. SSH-доступ и фактические OS/CPU/RAM/storage characteristics.
2. Наличие поддерживаемого server-side scheduler с реальным часовым событием.
3. Persistent state, которое сохраняет counter/timestamps после рестарта процесса probe.
4. Публичный read-only HTTP endpoint без credentials в URL и ответе.
5. Датированные server-side events и минимальную диагностику результата.
6. Возможность хранить runtime secrets вне Git и публичного web root.
7. Исходящий HTTPS-доступ, необходимый Metacritic и AI provider, без выполнения production scrape/AI batch в этом spike.

## Последовательность после предоставления доступа

### 1. Read-only preflight

Сначала без установок и изменений проверить:

- SSH host key и фактического пользователя;
- `/etc/os-release`, architecture и kernel;
- CPU/RAM, filesystem/free space и mount persistence;
- наличие `systemd`, timer support, journal retention и time synchronization;
- доступные непривилегированные ports, firewall/reverse-proxy state и внешний IP;
- наличие базового runtime (`python3`/shell), `curl` и `flock` либо эквивалентов;
- наличие `sudo` только как capability; не менять систему до фиксации точных targets.

Секреты и полный environment не печатать. Команды и evidence должны исключать IP, username, host key fingerprints и посторонние процессы/файлы, не относящиеся к probe.

### 2. Минимальное изменение

Если preflight подходит, создать отдельного least-privilege runtime user либо изолированный каталог, persistent state file и две минимальные OS units:

- oneshot job атомарно увеличивает counter и записывает UTC timestamp/run ID;
- hourly timer инициирует job server-side и имеет явный next/last trigger;
- read-only HTTP process отдаёт только sanitised probe state на согласованном публичном порту или через существующий reverse proxy.

Точные unit names, paths, port и команды фиксируются после read-only preflight. Не устанавливать application stack, database или production dependencies в рамках spike без отдельного обоснования.

### 3. Проверка

| Check | Объективный oracle |
|---|---|
| External reachability | Локальная машина получает `2xx` по public URL без SSH/VDS session |
| Server-side schedule | После реального часового trigger появились новый run ID и UTC timestamp; это не manual invocation |
| Persistence | Counter/state до и после restart HTTP/job process совпадает и продолжает расти |
| Diagnostics | Видны last trigger, last success/failure и связь события с run ID |
| Secret boundary | Public response, repository diff и sanitised logs не содержат `.env`, key, host/user или tokens |
| Resource headroom | Во время probe нет memory/storage exhaustion; фактические значения записаны без лишней host inventory |

Реальный scheduled event нельзя заменять ручным запуском. Ожидание часового окна считается календарным ожиданием, а не сфокусированной оценкой задачи.

### 4. Recovery и scope

- Перед изменением перечислить точные новые paths/units и проверить, что они не пересекаются с существующими сервисами.
- Не изменять существующие firewall, SSH и reverse-proxy rules без отдельного обоснования и согласования конкретного действия.
- Probe должен иметь точный rollback; удаление выполняется только для созданных им ресурсов.
- Если endpoint оставляется как ранняя основа deploy, это явно фиксируется вместо заявления о rollback.

## Критерий снятия Blocked

`SPK-06` становится исполнимой после появления заполненного локального `.env` и доступного key file. Она станет `Verified` только после внешнего HTTP check, process-restart check и фактического server-side scheduled event. До этого решение о пригодности VDS не выдано.
