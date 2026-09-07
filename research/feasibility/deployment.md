# `SPK-06` — проверка публичной среды

## Текущий статус

**Статус:** `Verified` — решение `Proceed with limitation`.

**Кандидат:** существующая VDS владельца. SSH-конфигурация была передана только через игнорируемый локальный `.env`; private key остался отдельным файлом. Host, username, key material и fingerprint не входят в evidence.

## Read-only preflight

Проверка выполнена 2026-09-07 до изменений на VDS.

| Capability | Фактический результат |
|---|---|
| ОС / architecture | Ubuntu 24.04, `x86_64` |
| CPU | 2 logical CPUs |
| RAM | 4,009,860 KiB, что соответствует заявленным 4 GB |
| Root filesystem | `ext4`; 82,446,168 KiB всего, 75,788,200 KiB доступно, 5% занято |
| Init / clock | `systemd` как PID 1; system state `running`; timezone `Europe/Amsterdam`; NTP synchronized |
| Базовые инструменты | `systemctl`, `systemd-run`, `journalctl`, Python 3.12, `curl`, `flock` доступны |
| Непривилегированный scheduler | `cron` установлен и активен; пользовательский `crontab` доступен |
| User services | user systemd manager запущен, но linger выключен |
| Privilege | non-interactive `sudo` недоступен |
| Persistent path | home directory доступен на запись на persistent `ext4` filesystem |
| Public ingress | непривилегированный TCP port `18080` был свободен и доступен извне после запуска probe |
| Outbound HTTPS | запрос с идентифицируемым допустимым User-Agent к странице Metacritic из VDS получил HTTP `200` |
| Provider traffic | заявленные владельцем 32 TB нельзя независимо подтвердить из guest OS; это не требовалось для capability probe |

Preflight подтвердил достаточный запас ресурсов и не обнаружил конфликта по target path, cron marker или порту. Существующие firewall, SSH, reverse-proxy rules, system packages и чужие процессы не изменялись.

## Реализованный probe

Исходники probe сохранены в [`probes/spk06/`](probes/spk06/):

- `probe_tick.py` под file lock атомарно обновляет persistent JSON, counter, scheduled counter, UTC timestamp и случайный run ID;
- `probe_http.py` публикует только `/health` и sanitised `/state`;
- `start_probe.sh` и `stop_probe.sh` управляют только процессом с проверенным PID/command line;
- `install_user_probe.sh` добавляет один маркированный блок в существующий пользовательский crontab и откатывает его, если HTTP probe не стартует.

Runtime создан только в `~/.local/share/metacritic-ai-probe`. Использованы уже доступные Python и cron; пакеты не устанавливались. Активная конфигурация probe:

```cron
0 * * * * /usr/bin/python3 <probe-root>/probe_tick.py hourly >> <probe-root>/timer.log 2>&1
@reboot <probe-root>/start_probe.sh >> <probe-root>/server.log 2>&1
```

Пути в фактическом crontab абсолютные; здесь home component заменён на `<probe-root>`, чтобы не публиковать username. HTTP слушает `0.0.0.0:18080`; публичный evidence использует `http://<redacted-host>:18080`, без credentials.

## Проверка

| UTC / этап | Объективный результат |
|---|---|
| 2026-09-07, install | Все пять переданных файлов совпали с локальными SHA-256; shell syntax и Python AST валидны; cron marker/hourly/reboot entries существуют ровно по одному |
| 2026-09-07, local VDS check | `GET /health` вернул `200`; initial state: `counter=1`, `scheduled_counter=0`, `last_event_origin=manual` |
| 2026-09-07, external check | Запрос с локальной машины без SSH получил `200` для `/health` и `/state`; неизвестный path получил `404` |
| 2026-09-07, response boundary | Payload имеет только allowlisted operational fields; `Cache-Control: no-store` и `X-Content-Type-Options: nosniff` присутствуют |
| 2026-09-07, process restart | HTTP-процесс получил новый PID; SHA-256 state file и counters не изменились; внешний `/state` остался доступен |
| 2026-09-07, isolated self-test | 16 конкурентных tick-процессов дали точные `counter=16` и `scheduled_counter=8`; временный HTTP endpoint прочитал state, live state не изменился, временный каталог удалён |
| 2026-09-07, resource/log check | HTTP RSS 20,732 KiB; весь probe 36 KiB; root filesystem сохранил 75,788,092 KiB свободного места; `server.log` и `timer.log` не содержали ошибок |
| 2026-09-07, long external polling | Четыре единичных connection reset восстановились на следующих polls; процесс оставался жив, state не менялся, `server.log` не содержал exception markers |
| 2026-09-07T06:00:01Z, scheduled event | Реальный cron trigger изменил state на `counter=2`, `scheduled_counter=1`, `origin=hourly`, `outcome=succeeded`; новый run ID присутствует; public и server-side state идентичны; state и zero-byte `timer.log` имеют одинаковый event timestamp |

Process-restart oracle выполнен: до и после рестарта состояние оставалось `counter=1`, `scheduled_counter=0`, `origin=manual`. Host reboot не выполнялся: текущий SSH-пользователь не имеет non-interactive `sudo`; установленный `@reboot` является recovery-механизмом probe, но его проверка остаётся для production deployment.

## Secret boundary и recovery

- `.env`, key path/value, host, username и fingerprint не записывались в репозиторий или публичный response.
- [`.gitignore`](../../.gitignore) исключает `.env`, `.env.*` и `/.secrets/`; [`.env.example`](../../.env.example) содержит только имена переменных.
- На VDS probe не потребовал и не сохранил credentials; state JSON содержит только имя/schema probe, counters, outcome, UTC timestamp и случайный run ID.
- Probe оставлен работающим как раннее доказательство публичной среды. Его rollback ограничен одним cron block между markers `BEGIN/END metacritic-ai-probe SPK-06`, проверенным PID и точным каталогом `~/.local/share/metacritic-ai-probe`.

## Решение и ограничения

**Решение:** `Proceed with limitation`. VDS подходит как среда для implementation baseline: подтверждены public ingress, persistent filesystem, process restart, пользовательский scheduler, датированное фоновое событие, диагностика, secret boundary и достаточный ресурсный запас.

Ожидаемые ограничения решения:

1. Probe использует user cron и `nohup`, потому что non-interactive `sudo` отсутствует, а systemd linger выключен. На `PLN-01` нужно выбрать production supervision/restart contract, явно применить business timezone UTC из `ASM-01` вместо системной зоны VDS и повторить host-reboot check до `G6`.
2. Порт probe работает по HTTP без TLS и предназначен только для не чувствительного read-only state. Production URL требует отдельного ingress/TLS решения.
3. Один фактический часовой trigger доказывает capability, но не удовлетворяет двухоконному `AC-RUN-01`; два последовательных окна и реальный application outcome проверяются в `PUB-02`.
4. Финальная доступность service URL повторно проверяется в `REL-04`; наблюдавшиеся восстановившиеся resets во время длительного polling не нарушают не заданный для probe SLO, но подтверждают необходимость retry/health monitoring и повторного внешнего smoke перед сдачей.
5. Доступ и contract бесплатной версии Grok проверяются отдельно в `SPK-05`.
