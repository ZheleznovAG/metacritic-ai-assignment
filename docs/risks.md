# Реестр рисков

## 1. Назначение и граница

Документ является результатом задачи `RSK-01`: риски обязательного и дополнительного scope выявлены, оценены, связаны с требованиями, допущениями, ранними сигналами, будущими проверками и владельцами.

В рамках исходной задачи `RSK-01` риски **не исследовались**. Последующие подтверждённые результаты spikes вносятся в этот же реестр отдельно; на 2026-09-04 добавлен результат `SPK-01`.

## 2. Шкалы и правила приоритета

Для каждого риска используются три независимые оценки от 1 до 5:

- `P` — предполагаемая вероятность реализации;
- `I` — влияние на сдачу обязательной части;
- `U` — текущая неопределённость до проверки.

Производные показатели:

- `Exposure = P × I` — ожидаемая опасность;
- `Discovery score = I × U` — насколько рано нужно получить факты.

Приоритет discovery:

| Приоритет | Правило |
|---|---|
| `P0` | Блокирует Must либо `Discovery score` 20–25 |
| `P1` | Существенно влияет на Must, `Discovery score` 12–19 |
| `P2` | Локализуемый риск Must, `Discovery score` до 11 |
| `B` | Изолирован внутри Bonus и не должен задерживать Must |

Если численная оценка спорит с прямым блокированием обязательного результата, применяется более высокий приоритет. После каждого spike оценки и текущая диспозиция обновляются фактическими данными.

Статусы:

- `Open — investigate` — требуется указанный spike;
- `Open — mitigate` — неизвестность невысока, риск закрывается проектированием и проверками;
- `Open — external decision` — исследование завершено, но дальнейшая работа требует внешнего разрешения или изменения условия;
- `Deferred bonus` — проверять только после ворот `G6`, если Bonus выбран;
- `Resolved` — есть evidence, решение и зафиксированный остаточный риск.

## 3. Очередь исследований

Очередь отсортирована по блокирующему влиянию, `Discovery score` и зависимостям. Одинаковый номер волны означает допустимую параллельность, а не уже начатую работу.

| Волна | Task | Закрываемые риски | Почему сейчас | Предусловие | Статус |
|---:|---|---|---|---|---|
| 1 | `SPK-01` | `R-EXT-01`, `R-EXT-02` | Без допустимого и воспроизводимого доступа основной источник может сделать весь Must нереализуемым | `RSK-01` | Verified — `Proceed with limitation` after resolved `Ask` |
| 2 | `SPK-02` | `R-EXT-03`, `R-EXT-04`, часть `R-SIM-01`, `R-TST-01` | Нужно подтвердить все поля и варианты страниц до модели данных и парсера | `SPK-01: Proceed*` | Verified — `Proceed with limitation` |
| 2 | `SPK-04` | `R-TIM-01`, `R-TIM-02` | Высокое влияние, но проверяется без сети на уже зафиксированных допущениях | `RSK-01` | Verified — `Proceed with limitation` |
| 2 | `SPK-06` | `R-DEP-01`, `R-DEP-02`, `R-OPS-01` | Публичная ссылка и реальный scheduler являются Must и опасны при поздней проверке | Выбрана существующая Ubuntu VDS | Verified — `Proceed with limitation` |
| 3 | `SPK-03` | `R-ID-01`, часть `R-DAT-01` | Правило identity зависит от фактических URL и платформенного контракта | `SPK-02: Proceed*` | Verified — `Proceed with limitation` |
| 3 | `SPK-05` | `R-AI-01`, `R-AI-02` | Eval требует репрезентативных отзывов или согласованного substitute | `SPK-02` либо допустимые samples | Verified — `Proceed with limitation`; `9/9` structural, `96/98` rubric |
| После `G6` | `BON-11` | `R-BON-YT-01`, `R-BON-YT-02` | Bonus не должен отнимать время у обязательного контура | Bonus 1 выбран | Deferred bonus |

`Proceed*` означает также `Proceed with limitation`, если ограничение не делает связанный Must недоказуемым.

## 4. Критические риски внешних зависимостей

### `R-EXT-01` Metacritic недоступен автоматическому клиенту

- **Связи:** `RUN-01`, `SEL-01–SEL-03`, `DATA-01–DATA-03`, `AI-01–AI-03`; `ASM-06–ASM-07`.
- **Проверяемый риск:** обе требуемые страницы или страницы игр блокируют автоматический доступ локально либо из публичной среды, требуют невоспроизводимой браузерной сессии или возвращают непригодный контент.
- **Оценка после `SPK-01`/`SPK-06`:** `P=2`, `I=5`, `U=3`; Exposure `10`, Discovery `15`; приоритет `P1`. Локальная доступность и HTTP `200` для репрезентативной страницы из VDS подтверждены; полный live contract и частота ещё не проверены.
- **Ранний сигнал:** 403/429/challenge, пустой HTML, контент появляется только после сложного client-side исполнения, локальный и cloud-ответы различаются.
- **Проверка:** `SPK-01`, минимальные повторяемые запросы/браузерные сценарии локально и в кандидатной среде.
- **Митигация:** допустимый способ получения, rate limit, timeout/backoff; при отсутствии пути — `Replan` или `Ask`, а не скрытая подмена источника.
- **Владелец:** `SPK-01`, затем `HRD-01/PUB-01`.
- **Evidence:** [`research/feasibility/metacritic-access.md`](../research/feasibility/metacritic-access.md).
- **Остаточный риск:** второй обязательный route, рабочая частота, Cloudflare и структура ответа могут отличаться от одиночного VDS-запроса.
- **Текущая диспозиция:** `Open — mitigate`; решение `Proceed with limitation` подтверждено локальной пробой, разрешением владельца и репрезентативным VDS-запросом; полный live contract остаётся у implementation/public checks.

### `R-EXT-02` Правила источника не допускают выбранный способ работы

- **Связи:** все требования Metacritic; `NFR-06`.
- **Проверяемый риск:** `robots.txt`, условия использования, ограничения частоты или показа контента конфликтуют с предполагаемым сбором, хранением или публичной демонстрацией.
- **Оценка после ответа владельца:** `P=2`, `I=5`, `U=2`; Exposure `10`, Discovery `10`; приоритет `P1` до проверки границ разрешения перед публикацией.
- **Ранний сигнал:** явный запрет пути/user-agent, условия против автоматизированного доступа или повторного использования материалов.
- **Проверка:** датированная проверка документов и поведения в `SPK-01`; спорное толкование не выдаётся за юридический факт.
- **Митигация:** минимальная частота и хранение, ссылки на источник, отказ от запрещённого способа; при блокирующем конфликте — `Ask/Replan`.
- **Владелец:** `SPK-01`, затем `REL-02`.
- **Evidence:** [`research/feasibility/metacritic-access.md`](../research/feasibility/metacritic-access.md).
- **Остаточный риск:** само разрешение не добавлено отдельным артефактом в репозиторий; перед release нужно сохранить доступное подтверждение scope и повторно проверить Terms/`robots.txt`.
- **Текущая диспозиция:** `Open — mitigate`; `Ask` разрешён ответом владельца 2026-09-05, решение `Proceed with limitation` в пределах сформулированного hourly access/storage/display scope.

### `R-EXT-03` Обязательные поля или отзывы фактически недоступны

- **Связи:** `DATA-02–DATA-03`, `AI-01–AI-03`, `UI-02`; `ASM-12`, `ASM-16–ASM-17`.
- **Проверяемый риск:** название, media, developer, description, video, платформенные оценки или один из видов отзывов отсутствуют, находятся в другом источнике/запросе, семантически подозрительны либо не могут быть однозначно сопоставлены игре.
- **Оценка после review `PLN-02`:** `P=4`, `I=5`, `U=3`; Exposure `20`, Discovery `15`; приоритет `P1`. Источники и null-contract подтверждены, но полнота review collection не доказана: принятый draft сохранял только одну подтверждённую страницу.
- **Ранний сигнал:** поле отсутствует в HTML, разные platform URLs несогласованы, вкладки отзывов загружаются отдельно, reported count превышает fetched count, next page меняет/повторяет набор либо title/description явно не соответствуют друг другу.
- **Проверка:** `SPK-02` на вариантах игр; переоткрытая `PLN-02` подтверждает pagination/cursor, ordering, exhaustion, duplicates и reported-versus-fetched counts для critic/user routes.
- **Митигация:** составной JSON-LD + DOM contract; bounded platform-specific pagination; явные coverage counters и exhaustion reason; классифицировать естественное отсутствие отдельно от parser failure; хранить provenance; семантическую аномалию не «исправлять» выдуманным значением.
- **Владелец:** `SPK-02/PLN-02`, затем `HRD-01`.
- **Остаточный риск:** critic/user routes могут иметь разные или меняющиеся pagination semantics; отдельные будущие игры могут иметь новый вариант представления или ошибочные данные источника.
- **Текущая диспозиция:** `Open — investigate`; `PLN-02: Changes requested`, существующее evidence: [`research/feasibility/metacritic-contract.md`](../research/feasibility/metacritic-contract.md).

### `R-EXT-04` Изменчивость разметки молча портит данные

- **Связи:** `DATA-01–DATA-03`, `NFR-04`; `ASM-11–ASM-12`.
- **Проверяемый риск:** A/B-варианты, locale, отсутствие поля или изменение DOM приводят не к заметной ошибке, а к пустым либо неверно сопоставленным значениям и затиранию хороших данных.
- **Оценка после `SPK-02`:** `P=5`, `I=4`, `U=3`; Exposure `20`, Discovery `12`; приоритет `P1`. Mutable lists, overlap и внутренне разные review counts уже наблюдались.
- **Ранний сигнал:** резкое падение completeness, одинаковые значения платформ, массовые null, fixture-варианты дают разные структуры, соседние страницы повторяют URL или source sections противоречат друг другу.
- **Проверка:** варианты и fixtures в `SPK-02`; позднее contract/failure tests `HRD-01`.
- **Митигация:** граничная валидация, parser contract, provenance, дневная дедупликация, защита от destructive partial update, отдельный live check.
- **Владелец:** `SPK-02`, затем `HRD-01`.
- **Остаточный риск:** fixture не предсказывает все будущие изменения сайта.
- **Текущая диспозиция:** `Open — mitigate`; ранние варианты и overlap сохранены в fixtures `SPK-02`, executable failure checks остаются у `HRD-01`.

### `R-AI-01` AI-резюме не проходит качественный контракт

- **Связи:** `AI-01–AI-03`; `ASM-16–ASM-19`.
- **Проверяемый риск:** модель смешивает критиков и пользователей, выдумывает тезисы, преувеличивает единичное мнение, нарушает формат или следует инструкциям из отзывов.
- **Оценка после `SPK-05`:** `P=2`, `I=5`, `U=2`; Exposure `10`, Discovery `10`; приоритет `P1`. Замороженный baseline прошёл `96/98` без blocker, но модель принята только в консервативном extractive режиме.
- **Ранний сигнал:** ошибки на контрастных, sparse или инструктивных samples; нестабильный формат между повторами.
- **Проверка:** `SPK-05` с замороженным eval-набором, рубрикой, блокирующими ошибками и baseline; immutable corpus/attempt/claim contracts в `PLN-02`; executable regression — `IMP-04/HRD-04`.
- **Митигация:** все скачанные отзывы хранятся отдельно от точного immutable model corpus; аудитории не смешиваются; один `review_corpus_item` полностью подтверждает каждый тезис; structured output проходит локальную canonical validation, deterministic five-item cap, token-aware preflight, prompt hardening и честное insufficient-data состояние. Model, contour versions/hashes, UTC-время и outcome каждой попытки сохраняются.
- **Владелец:** `SPK-05`, затем `IMP-04/HRD-04`.
- **Остаточный риск:** модель не доказана на production-maximum input; другие и смешанные языки требуют boundary fixtures; иногда пропускаются вторичные темы или добавляется подтверждённый шум; provider fingerprints различаются.
- **Текущая диспозиция:** `Open — mitigate`; `SPK-05: Verified — Proceed with limitation`, а review/corpus policy возвращена в `Candidate` до token-boundary evidence в `PLN-02` и executable `IMP-04/HRD-04` checks.

### `R-AI-02` AI-провайдер непригоден по доступу, цене или задержке

- **Связи:** `AI-01–AI-03`, `RUN-01`; `CTX-03`, `CTX-06`, `ASM-19`.
- **Проверяемый риск:** нет credentials, лимит/стоимость контекста неприемлемы для 20 игр в час, latency превышает окно, rate limit делает обработку нестабильной.
- **Оценка после `SPK-05`:** `P=5`, `I=4`, `U=1`; Exposure `20`, Discovery `4`; приоритет `P1` как известное ограничение. Доступ и latency подтверждены, но опубликованный Free TPD не покрывает теоретический cold-path максимум.
- **Ранний сигнал:** отсутствующий доступ, высокая оценка токенов, частые 429, timeout на небольшом sample.
- **Проверка:** измерения количества входа, latency, rate limits и стоимости в `SPK-05` без запуска полного production batch.
- **Подтверждённый кандидат:** Groq Free Plan, `openai/gpt-oss-20b`, Chat Completions API. Финальный run: `9/9` responses, `11,687` total tokens, median `7.638s`, max `12.134s`; опубликованы `30 RPM`, `1,000 RPD`, `8,000 TPM`, `200,000 TPD`.
- **Митигация:** `PLN-01` выбрала PostgreSQL-backed `SummaryJob` без Redis/Celery; candidate `PLN-02` contract использует unique cache, один worker, bounded retry/delayed capacity и запрет paid fallback. До принятия corpus policy обязателен token-aware preflight по TPM/context/output budgets и worst-case multilingual fixture.
- **Владелец:** `SPK-05/PLN-01–PLN-02`, затем `IMP-04/HRD-04`.
- **Остаточный риск:** при наблюдаемом среднем размере Free TPD покрывает примерно 154 audience summaries/77 games в день против теоретических 960 summaries; тарифы, квоты, latency и доступность меняются внешне.
- **Текущая диспозиция:** `Open — mitigate`; storage/worker contour принят в [`ADR-0001`](decisions/0001-minimal-stack-and-architecture.md), job/cache/retry states остаются candidate design в [`docs/design.md`](design.md). Реализация и token-boundary evidence обязательны; устойчивый объём выше capacity требует `Replan` до заявления production throughput.

### `R-DEP-01` Публичная среда не поддерживает обязательный runtime

- **Связи:** `RUN-01`, `DEL-02`, `NFR-01`, `NFR-05`; `CTX-03`, `CTX-05–CTX-06`.
- **Проверяемый риск:** кандидатная площадка усыпляет сервис, не поддерживает почасовой scheduler, постоянное состояние, секреты или диагностические события.
- **Оценка после `SPK-06`:** `P=2`, `I=5`, `U=2`; Exposure `10`, Discovery `10`; приоритет `P1`. Persistent `ext4`, user cron, public ingress, process restart и реальное фоновое событие подтверждены; production supervision и host reboot ещё не проверены.
- **Ранний сигнал:** ephemeral filesystem, запрет cron/background worker, sleep меньше часа, недоступные logs/secrets.
- **Проверка:** минимальный публичный probe `SPK-06` на выбранной Ubuntu 24.04 VDS с внешним HTTP check, перезапуском и реальным фоновым событием; preflight contract в [`deployment.md`](../research/feasibility/deployment.md).
- **Митигация:** `PLN-01` выбрала Docker Compose: Caddy, Gunicorn/Django web, UTC scheduler, один enrichment worker и PostgreSQL с named volumes; до `G4` проверить Engine/Compose и deploy permission, до `G6` — DNS/80/443, volume persistence, host reboot и два application schedule windows; при утрате capability выбрать иной hosting/managed scheduler/persistent store.
- **Владелец:** `SPK-06/PLN-01`, затем `IMP-01/PUB-01–PUB-02`.
- **Остаточный риск:** Docker/Compose и право deploy-user управлять daemon на VDS не подтверждены; non-interactive `sudo` недоступен, hostname и 80/443 ещё не проверены; host reboot, memory budget и volume lifecycle требуют evidence.
- **Текущая диспозиция:** `Open — mitigate`; production contour принят в [`ADR-0001`](decisions/0001-minimal-stack-and-architecture.md), но public deployment нельзя считать доказанным до `PUB-01–PUB-02`.

### `R-DEP-02` Ссылки доступны автору, но не проверяющему

- **Связи:** `DEL-01–DEL-03`; `ASM-24`.
- **Проверяемый риск:** repository/service/archive требуют локальную сессию, приглашение, истёкший URL или скрытый секрет.
- **Оценка после `SPK-06`:** `P=2`, `I=5`, `U=2`; Exposure `10`, Discovery `10`; приоритет `P1`. Read-only endpoint открылся с внешней машины без SSH/session/credentials; финальные service/repository/archive URLs ещё не существуют.
- **Ранний сигнал:** доступ работает только в авторизованном браузере, URL содержит localhost/private network, archive не опубликован.
- **Проверка:** первоначальная проверка модели доступа в `SPK-06`; финальная — `REL-04` из внешней сессии.
- **Митигация:** явный read-only доступ, стабильные URL, повторный link-check непосредственно перед отправкой.
- **Владелец:** `SPK-06`, затем `REL-04`.
- **Остаточный риск:** probe использует redacted raw HTTP endpoint, а финальная ссылка или аккаунт могут стать недоступны после сдачи.
- **Текущая диспозиция:** `Open — mitigate`; базовая модель внешнего доступа подтверждена `SPK-06`, финальный внешний check остаётся у `REL-04`.

## 5. Критические риски состояния и бизнес-правил

### `R-ID-01` Неверная identity создаёт дубли или сливает разные игры

- **Связи:** `DATA-01`, `DATA-03`, `SEL-01–SEL-03`; `ASM-10`, `ASM-13`.
- **Проверяемый риск:** title, slug или URL меняются/повторяются, а платформенные страницы ошибочно трактуются как отдельные игры либо разные игры объединяются.
- **Оценка после `SPK-03`:** `P=2`, `I=5`, `U=2`; Exposure `10`, Discovery `10`; приоритет `P1` до автоматической проверки unique/conflict branches. Источник публикует game/platform IDs, но их долговременная стабильность не документирована.
- **Ранний сигнал:** один title имеет разные canonical URLs, URL включает platform, одинаковый slug ведёт к разным объектам.
- **Проверка:** `SPK-03` на list/detail/review matches, пяти платформенных вариантах, близких названиях и конфликтных переходах; позднее integration/concurrency tests.
- **Митигация:** ID-first identity `(source, source_game_id)`, platform membership `(game, source_platform_id)`, `relatedGameId` assertion, locator aliases, unique constraints и запрет эвристического merge.
- **Владелец:** `SPK-03`, затем `IMP-01–IMP-02` и `HRD-02–HRD-03`.
- **Evidence:** [`research/feasibility/game-identity.md`](../research/feasibility/game-identity.md) и [`identity-cases.json`](../research/feasibility/fixtures/metacritic/identity-cases.json).
- **Остаточный риск:** недокументированные SSR IDs могут исчезнуть, измениться или конфликтовать с reused locator; такая запись должна остановиться заметной ошибкой до update.
- **Текущая диспозиция:** `Open — mitigate`; `SPK-03: Proceed with limitation`, финальное доказательство — unique/upsert/conflict/concurrency tests.

### `R-TIM-01` Дневная семантика приводит к пропускам или повторной выборке

- **Связи:** `RUN-01`, `SEL-01–SEL-03`; `ASM-01–ASM-09`.
- **Проверяемый риск:** трактовки лимита, processed, retry, первого запуска, page cursor, исчерпания и смены дня противоречат друг другу на граничном сценарии.
- **Оценка после `SPK-04`:** `P=2`, `I=5`, `U=2`; Exposure `10`, Discovery `10`; приоритет `P1` сохраняется до автоматической проверки критического бизнес-инварианта.
- **Ранний сигнал:** невозможно однозначно назвать следующую партию по заданному состоянию; один кандидат появляется дважды или теряется.
- **Проверка:** таблица переходов и бумажные сценарии `SPK-04` с fake time.
- **Митигация:** единая state model, разделение discovery и enrichment, явная business timezone, детерминированный selector.
- **Владелец:** `SPK-04`, затем `IMP-03/HRD-02`.
- **Evidence:** [`research/feasibility/processing-state.md`](../research/feasibility/processing-state.md).
- **Остаточный риск:** live source может менять порядок перед сохранённым cursor; pagination/identity известны, но mutable source не гарантирует snapshot и требует selector tests.
- **Текущая диспозиция:** `Open — mitigate`; решение `Proceed with limitation`, окончательная проверка — selector/state tests после выбора стека.

### `R-TIM-02` Рестарт или пересечение запусков нарушает прогресс

- **Связи:** `RUN-01`, `SEL-01–SEL-03`, `NFR-01`, `NFR-03`; `ASM-02`, `ASM-04–ASM-05`, `ASM-09`.
- **Проверяемый риск:** два запуска выбирают одну работу, crash теряет владение/курсор либо незавершённая запись навсегда считается успешной.
- **Оценка после `SPK-04`:** `P=3`, `I=5`, `U=2`; Exposure `15`, Discovery `10`; приоритет `P1` сохраняется до failure/concurrency evidence.
- **Ранний сигнал:** состояния нельзя восстановить только из persistent data; нет различия attempt/success/failure; duplicate counters.
- **Проверка:** сначала модель `SPK-04`, затем failure/concurrency tests `HRD-02–HRD-03`.
- **Митигация:** PostgreSQL хранит unique UTC trigger key, daily candidate/checkpoint, attempts и singleton lease с 45-минутным TTL, heartbeat и monotonic fencing token; core success проверяет текущий token и коммитит upsert/attempt/candidate state одной транзакцией.
- **Владелец:** `SPK-04/PLN-01–PLN-02`, затем `IMP-03/HRD-02–HRD-03`.
- **Evidence:** [`research/feasibility/processing-state.md`](../research/feasibility/processing-state.md).
- **Остаточный риск:** контракт ещё не подтверждён executable concurrency/crash tests; любое изменение ownership query или границы транзакции требует повторного invariant test.
- **Текущая диспозиция:** `Open — mitigate`; точные состояния и транзакционные инварианты приняты в [`docs/design.md`](design.md), executable evidence остаётся у `IMP-03/HRD-02–HRD-03`.

### `R-DAT-01` Частичная обработка повреждает хорошее состояние

- **Связи:** `DATA-01–DATA-03`, `AI-03`, `NFR-02`, `NFR-04`; `ASM-11–ASM-12`, `ASM-22`.
- **Проверяемый риск:** пустой parser result, сбой на платформе или AI-ошибка затирают валидные поля, откатывают успешные элементы либо оставляют неразличимый partial state.
- **Оценка:** `P=3`, `I=5`, `U=3`; Exposure `15`, Discovery `15`; приоритет `P1`.
- **Ранний сигнал:** update принимает null без provenance, batch имеет одну общую транзакцию, status только boolean.
- **Проверка:** full/incomplete fixtures `SPK-02`, identity/conflict transitions `SPK-03`; окончательно failure tests `HRD-01–HRD-02`.
- **Митигация:** identity validation до commit, scoped atomic update, non-destructive merge policy, отсутствие platform не означает delete; каждый fetch имеет outcome/hash/provenance, отзывы и их observations immutable, а review/summary jobs отделены от core success.
- **Владелец:** `SPK-02–SPK-03/PLN-02`, затем `IMP-02–IMP-04/HRD-01–HRD-02`.
- **Остаточный риск:** новое семантически неверное, но формально валидное значение может пройти schema validation.
- **Текущая диспозиция:** `Open — mitigate`; non-destructive transaction и review provenance contract принят в [`docs/design.md`](design.md), executable destructive-update tests остаются у `HRD-01–HRD-02`.

### `R-SIM-01` Похожие игры формально работают, но нерелевантны

- **Связи:** `SIM-01–SIM-03`; `ASM-20–ASM-21`.
- **Проверяемый риск:** доступные поля недостаточны для осмысленной похожести или алгоритм возвращает self-match, внешние записи и случайные результаты.
- **Оценка после `SPK-02`/`RSK-02`:** `P=3`, `I=4`, `U=2`; Exposure `12`, Discovery `8`; приоритет `P2`. Доступны title, description, developer, platform и genre; оставшийся выбор метода локализован в design/eval и не требует нового внешнего spike.
- **Ранний сигнал:** у страниц нет жанров/признаков, очевидные пары не сближаются, результат меняется без изменения данных.
- **Проверка:** доступные признаки в `SPK-02`; candidate `0.1.0` в `PLN-02`; независимые examples/metric/threshold/invariants — `SIM-EVAL-01`; comparison — `IMP-06`; integration — `SIM-VER-01`.
- **Митигация:** сначала заморозить quality oracle, затем без его изменения сравнить candidate score по genre/platform/developer как минимум с простым baseline, выбрать простейший проходящий вариант и отдельно проверить hard self/duplicate/external exclusions и UI navigation.
- **Владелец:** `SPK-02/PLN-02`, затем `SIM-EVAL-01/IMP-06/SIM-VER-01`.
- **Остаточный риск:** субъективность релевантности на малом наборе.
- **Текущая диспозиция:** `Open — mitigate`; формула понижена до candidate `0.1.0` в [`docs/design.md`](design.md). Policy не может стать accepted до frozen oracle и comparison evidence; новый внешний сервис не требуется.

## 6. Риски доказуемости, поставки и безопасности

### `R-OPS-01` Нельзя доказать фактическую почасовую работу

- **Связи:** `RUN-01`, `NFR-05`, `DEL-02`.
- **Проверяемый риск:** scheduler настроен, но в публичной среде нет надёжного server-side свидетельства запуска, итогов и последнего успеха.
- **Оценка после `SPK-06`:** `P=2`, `I=5`, `U=2`; Exposure `10`, Discovery `10`; приоритет `P1`. Persistent state сохранил counters/timestamp/run ID реального cron-события; полный application outcome и retention ещё не реализованы.
- **Ранний сигнал:** доступны только console logs без времени/run ID, hosting скрывает историю, UI показывает локально вычисленный статус.
- **Проверка:** capability/probe в `SPK-06`; operational contract в `HRD-05/PUB-02`.
- **Митигация:** `processing_run`, `core_attempt`, review/summary jobs и неизменяемые после terminal outcome AI attempts хранят timestamps, outcomes, counters/errors и корреляцию в PostgreSQL; bounded structured logs дополняют, но не заменяют состояние.
- **Владелец:** `SPK-06`, затем `HRD-05/PUB-02`.
- **Остаточный риск:** один capability event не доказывает два последовательных application windows по `AC-RUN-01`; raw HTTP дал несколько восстановившихся network resets; production retention/monitoring ещё не выбраны.
- **Текущая диспозиция:** `Open — mitigate`; persistent operational contract принят в [`docs/design.md`](design.md), а два последовательных application windows, retention и публичная диагностика остаются у `HRD-05/PUB-02`.

### `R-TST-01` Проверки нестабильны из-за живых внешних сервисов

- **Связи:** все требования Metacritic и AI; `NFR-04`, `NFR-06`.
- **Проверяемый риск:** обычный CI зависит от текущего Metacritic, платной модели, сети или mutable данных и даёт ложные падения/успехи.
- **Оценка:** `P=4`, `I=3`, `U=3`; Exposure `12`, Discovery `9`; приоритет `P2`.
- **Ранний сигнал:** один тест проходит повторно без изменения кода, расходует API budget или требует secrets.
- **Проверка:** Metacritic contract fixtures определены в `SPK-02`; frozen AI cases/schema/runner — в `SPK-05`; executable fake-provider suite создаётся в `HRD-06`, live contract запускается отдельно.
- **Митигация:** deterministic fixtures/mocks, замороженные eval inputs, отдельные контролируемые live checks.
- **Владелец:** `SPK-02/SPK-05`, затем `HRD-06`.
- **Остаточный риск:** offline suite не гарантирует текущую совместимость; её покрывает отдельный live check.
- **Текущая диспозиция:** `Open — mitigate`; curated Metacritic fixtures и frozen AI cases сохранены, executable sanitised HTML/fake-provider suite ещё нужен в `HRD-06`.

### `R-SEC-01` Секреты или недоверенный контент попадают в публичные артефакты

- **Связи:** `NFR-06`, `DEL-01–DEL-03`, все AI/UI требования; `ASM-26`.
- **Проверяемый риск:** API keys оказываются в Git/log/AI history/client bundle либо внешний HTML/отзывы/AI-output небезопасно отображаются.
- **Оценка:** `P=3`, `I=5`, `U=2`; Exposure `15`, Discovery `10`; приоритет `P2`, но блокирующий перед публикацией.
- **Ранний сигнал:** committed env, token-like strings, raw HTML rendering, prompts содержат credentials.
- **Проверка:** config review и security tests `HRD-05`; automated/manual scan `REL-03`.
- **Митигация:** secrets management, redaction policy, output escaping/sanitization, минимальные permissions.
- **Владелец:** непрерывно; формально `HRD-05/REL-03`.
- **Остаточный риск:** scanner не распознает новый формат секрета; требуется ручное review.
- **Текущая диспозиция:** `Open — mitigate`.

### `R-DEL-01` AI-архив окажется неполным или непубликуемым

- **Связи:** `DEL-03`; `CTX-14`, `ASM-23`, `ASM-26`.
- **Проверяемый риск:** часть сессий не экспортируется, исходный порядок потерян, raw JSONL отсутствует, либо история содержит сведения, которые нельзя публиковать.
- **Оценка:** `P=4`, `I=4`, `U=3`; Exposure `16`, Discovery `12`; приоритет `P1`.
- **Ранний сигнал:** AI-работа существует только в клиенте, нет manifest, разные форматы не имеют времени/порядка.
- **Проверка:** периодический inventory; финальный manifest и privacy/secret review `REL-03`.
- **Митигация:** сохранять prompts/results по ходу, не передавать секреты модели, документировать формат и вынужденные изъятия.
- **Владелец:** непрерывно; формально `REL-03`.
- **Остаточный риск:** платформа может не предоставлять полный raw export; ограничение нужно обозначить честно.
- **Текущая диспозиция:** `Open — mitigate`.

### `R-PLN-01` Неизвестные срок, ёмкость и бюджет делают scope нереалистичным

- **Связи:** весь scope; `CTX-01–CTX-06`.
- **Проверяемый риск:** implementation baseline включает больше работы/расходов, чем доступно, а Bonus вытесняет обязательную проверку и deploy.
- **Оценка:** `P=4`, `I=4`, `U=4`; Exposure `16`, Discovery `16`; приоритет `P1`.
- **Ранний сигнал:** нет календарного резерва, задачи остаются `TBE`, выбран платный dependency без бюджета.
- **Проверка:** запрос рамок при доступном канале; capacity/scope review в `PLN-03`.
- **Митигация:** относительные оценки до ответа, Must-first, отдельный резерв сдачи, Bonus только после `G6`, отсутствие необратимых расходов.
- **Владелец:** владелец проекта и `PLN-03`.
- **Остаточный риск:** без дедлайна нельзя дать календарное обещание, но можно сохранять правильный порядок работы.
- **Текущая диспозиция:** `Open — mitigate`; не блокирует ближайшие spikes без затрат.

### `R-REP-01` Репозиторий или запуск невоспроизводимы

- **Связи:** `DEL-01`, `NFR-06`.
- **Проверяемый риск:** проект работает только в текущей машине из-за скрытой конфигурации, ручных шагов, локальных данных или незадокументированных версий.
- **Оценка:** `P=3`, `I=4`, `U=3`; Exposure `12`, Discovery `12`; приоритет `P1`.
- **Ранний сигнал:** setup не выполнялся с чистого checkout, отсутствует config template, state создаётся вручную.
- **Проверка:** ранний reproducible bootstrap `IMP-01`, окончательный clean-run `REL-01–REL-02`.
- **Митигация:** `PLN-01` зафиксировала canonical Python 3.12, Django 5.2 LTS, PostgreSQL 16, один application image, Compose production contour, `pyproject.toml`, exact resolved lock и project-local `.venv`; локальный Docker Engine подтверждён. Миграции, конфигурационный шаблон, seed/fixtures, исполнимые README-команды и CI создаются в `IMP-01`.
- **Владелец:** `IMP-01`, затем `REL-01–REL-02`.
- **Остаточный риск:** внешние package registries/hosting остаются изменчивыми.
- **Текущая диспозиция:** `Open — mitigate`.

### `R-UI-01` UI выполняет функции по отдельности, но не общий сценарий

- **Связи:** `UI-01–UI-05`, `SIM-02–SIM-03`, `DEL-02`; `ASM-15`, `ASM-24–ASM-25`.
- **Проверяемый риск:** поиск, фильтр, сортировка и навигация конфликтуют; null/multiplatform/long-title состояния ломают карточку или список.
- **Оценка:** `P=3`, `I=3`, `U=2`; Exposure `9`, Discovery `6`; приоритет `P2`.
- **Ранний сигнал:** функции тестируются только изолированно, filter теряется при sort/navigation, ошибки видны только на реальных данных.
- **Проверка:** acceptance cases `AC-UI-01–AC-UI-06`, обязательный E2E `IMP-07/PUB-03`.
- **Митигация:** один комбинированный путь и фиксированные edge-case seeds вместо большого числа несвязанных UI unit tests.
- **Владелец:** `IMP-05/IMP-07`.
- **Остаточный риск:** вне принятой browser baseline возможны визуальные отличия.
- **Текущая диспозиция:** `Open — mitigate`.

## 7. Риски дополнительных частей

### `R-BON-YT-01` Нельзя надёжно найти и ранжировать летсплей

- **Связи:** `YT-01`; `ASM-B01`, `CTX-03`, `CTX-06`.
- **Проверяемый риск:** YouTube search недоступен без credentials/quota, view count нельзя получить надёжно или запрос возвращает trailers/reviews вместо летсплеев.
- **Оценка:** `P=4`, `I=1` относительно Must, `U=5`; Exposure `4`, Discovery `5`; влияние внутри Bonus 1 — `5`; приоритет `B`.
- **Ранний сигнал:** неоднозначные названия игр, нет quota, неполные metrics, нерелевантные top results.
- **Проверка:** `BON-11` только после выбора Bonus 1.
- **Митигация:** явные query/filter rules; при непройденном gate — `Drop bonus`.
- **Владелец:** `BON-11`.
- **Остаточный риск:** выдача и view count изменяются со временем.
- **Текущая диспозиция:** `Deferred bonus`.

### `R-BON-YT-02` Текст произвольного видео недоступен или непригоден

- **Связи:** `YT-01`; `ASM-B02`.
- **Проверяемый риск:** captions отсутствуют/закрыты, допустимый transcript нельзя получить, язык/качество не позволяют grounded conclusion, объём слишком дорог.
- **Оценка:** `P=4`, `I=1` относительно Must, `U=5`; Exposure `4`, Discovery `5`; влияние внутри Bonus 1 — `5`; приоритет `B`.
- **Ранний сигнал:** выбранное популярное видео без captions, API требует права владельца, ASR time/cost выше бюджета.
- **Проверка:** `BON-11` на нескольких видео.
- **Митигация:** честное unavailable state; при отсутствии устойчивого допустимого пути — `Drop bonus`.
- **Владелец:** `BON-11`, затем `BON-12`.
- **Остаточный риск:** доступность текста различается для каждой игры.
- **Текущая диспозиция:** `Deferred bonus`.

### `R-BON-OPS-01` Monitoring показывает несогласованное или фиктивное состояние

- **Связи:** `OPS-01`; `ASM-B03`.
- **Проверяемый риск:** UI вычисляет прогресс локально, теряет события или показывает статус, не совпадающий с persistent run record.
- **Оценка:** `P=3`, `I=1` относительно Must, `U=3`; Exposure `3`, Discovery `3`; влияние внутри Bonus 2 — `4`; приоритет `B`.
- **Ранний сигнал:** refresh меняет/сбрасывает статус, финальный counter расходится с серверным, нет единого run ID.
- **Проверка:** `BON-21` сопоставлением UI и server-side событий.
- **Митигация:** единый источник истины, snapshot + обновления, измеримый freshness contract.
- **Владелец:** `BON-21`.
- **Остаточный риск:** временная потеря связи может задержать отображение, но не должна менять состояние процесса.
- **Текущая диспозиция:** `Deferred bonus`.

### `R-BON-OPS-02` Ручной запуск создаёт дубль или открыт для злоупотребления

- **Связи:** `OPS-02`, `NFR-03`; `ASM-B04`.
- **Проверяемый риск:** повторный клик/параллельный scheduler создаёт второй run либо публичная кнопка позволяет расходовать внешние квоты неавторизованно.
- **Оценка:** `P=3`, `I=2` относительно Must при включённом Bonus, `U=3`; Exposure `6`, Discovery `6`; влияние внутри Bonus 2 — `5`; приоритет `B`, блокирующий выпуск Bonus 2.
- **Ранний сигнал:** endpoint не имеет access/rate/idempotency policy, каждый click создаёт новый job.
- **Проверка:** `BON-22` auth, abuse и concurrency scenarios.
- **Митигация:** явная модель доступа, server-side idempotency/ownership, reuse основного pipeline.
- **Владелец:** `BON-22`.
- **Остаточный риск:** скомпрометированный разрешённый доступ; ограничивается rate/audit policy.
- **Текущая диспозиция:** `Deferred bonus`.

## 8. Аудит покрытия `RSK-01`

### Внешние зависимости

| Зависимость | Риски | Владелец проверки | Покрытие |
|---|---|---|---|
| Metacritic | `R-EXT-01–R-EXT-04` | `SPK-01–SPK-02` | `SPK-02: Proceed with limitation`; финальный live contract остаётся |
| Runtime LLM | `R-AI-01–R-AI-02` | `SPK-05`, затем `IMP-04/HRD-04` | `SPK-05: Proceed with limitation`; качество пройдено, Free TPD и extractive policy назначены на митигацию |
| Публичный hosting/storage/scheduler | `R-DEP-01–R-DEP-02`, `R-OPS-01` | `SPK-06`, затем `HRD-05/PUB-02/REL-04` | `SPK-06: Proceed with limitation`; capability подтверждена, production checks назначены |
| Git repository / AI archive | `R-DEP-02`, `R-DEL-01`, `R-REP-01` | непрерывно, `REL-01–REL-04` | Покрыто задачами поставки |
| YouTube | `R-BON-YT-01–R-BON-YT-02` | `BON-11` | Изолировано до выбора Bonus 1 |

### Критические инварианты

| Инвариант | Риски | Следующая проверка | Покрытие |
|---|---|---|---|
| Почасовая работа доказуема | `R-DEP-01`, `R-OPS-01` | `HRD-05/PUB-02` после capability probe `SPK-06` | Один реальный cron event проверен; нужны два application windows и outcome |
| Дневная выборка однозначна | `R-TIM-01` | `HRD-02` после реализации модели `SPK-04` | Модель проверена на бумажных сценариях; нужен automated evidence |
| Рестарт и пересечение безопасны | `R-TIM-02` | `HRD-02–HRD-03`, deployment restart | Модель проверена; нужен failure/concurrency evidence |
| Игра и платформы не дублируются | `R-ID-01` | `IMP-01–IMP-02`, `HRD-02–HRD-03` после `SPK-03` | ID-first contract и коллизии проверены; нужны executable unique/concurrency tests |
| Частичный ответ не портит данные | `R-EXT-04`, `R-DAT-01` | `SPK-02`, позднее `HRD-01–HRD-02` | Есть ранняя и финальная проверка |
| AI grounded и разделяет аудитории | `R-AI-01` | `IMP-04/HRD-04` после baseline `SPK-05` | `9/9` structural, rubric `96/98`, `0` blockers; нужны executable provider-fake/regression tests |
| Similarity не формальна | `R-SIM-01` | `SIM-EVAL-01/IMP-06/SIM-VER-01` после исправления `PLN-02` | Stored-feature formula остаётся candidate; oracle замораживается до comparison |
| UI работает единым сценарием | `R-UI-01` | `IMP-07/PUB-03` | Не требует отдельного spike |
| Сдача воспроизводима и безопасна | `R-SEC-01`, `R-DEL-01`, `R-REP-01` | implementation/release tasks | Есть непрерывная митигация |

### Проверка критерия выхода

- [x] Каждый внешний источник представлен конкретным риском.
- [x] Каждый критический инвариант представлен риском либо обоснованно направлен в реализационную проверку.
- [x] У каждого риска есть вероятность/влияние или изолированная Bonus-оценка.
- [x] У каждого риска есть ранний сигнал, проверка, митигация, владелец и остаточный риск.
- [x] Must-spikes отсортированы по неизвестности, влиянию и зависимостям.
- [x] Bonus-риски не блокируют Must.
- [x] Ни один spike не был выполнен в рамках `RSK-01`.

**Итог `RSK-01`:** реестр и очередь исследований созданы; `SPK-01–SPK-06` впоследствии завершены решениями `Proceed with limitation`.

## 9. Итоговая проверка `RSK-02`

- Проверено 24 risk blocks: 20 Must и 4 Bonus.
- У всех 20 Must-рисков есть проверка, митигация, владелец, остаточный риск и текущая диспозиция.
- После spikes нет текущих рисков `P0`, решений `Replan` или незакрытых `Blocked / Ask`.
- 16 рисков `P1` и 4 риска `P2` переданы конкретным design/implementation/hardening/public/release задачам.
- Все 4 Bonus-риска имеют приоритет `B`, статус `Deferred bonus` и не влияют на `G2`.
- `R-SIM-01` переведён из внешнего исследования в design/eval mitigation: признаки подтверждены, oracle фиксируется в `SIM-EVAL-01`, а method выбирается только затем в `IMP-06`.

**Решение:** `G2` пройдены с ограничениями; подробная матрица evidence, остаточных рисков, владельцев и stop conditions находится в [`requirements/g2_review.md`](requirements/g2_review.md). На момент `RSK-02` следующей задачей была `PLN-01`; принятое решение теперь находится в [`ADR-0001`](decisions/0001-minimal-stack-and-architecture.md).
