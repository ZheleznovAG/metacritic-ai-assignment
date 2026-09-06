# `SPK-04` — модель времени, партий и прогресса

## Вопрос, граница и решение

**Вопрос:** можно ли однозначно определить следующий запуск и итоговое состояние для первого и последующих запусков дня, смены даты, частичной ошибки, рестарта, повтора trigger и пересечения запусков?

**Решение:** `Proceed with limitation`.

Логическая модель ниже достаточна для написания детерминированных тестов до реализации. Она не выбирает язык, базу данных, scheduler или механизм блокировки. Контракт страниц подтверждён `SPK-02`, фактический game key и platform identity — `SPK-03`; конкретные scheduler/lease capabilities публичной среды остаются зависимостью `SPK-06`.

**Связи:** `RUN-01`, `SEL-01–SEL-03`, `DATA-01`, `NFR-01–NFR-03`; Bonus `OPS-02`; `ASM-01–ASM-09`, `ASM-22`; `R-TIM-01–R-TIM-02`.

## Термины

| Термин | Однозначное значение в модели |
|---|---|
| Instant | Момент на временной шкале, сохраняемый в UTC |
| Business timezone | Конфигурируемая IANA-зона; до уточнения используется UTC по `ASM-01` |
| Business day | Локальная календарная дата `instant` в business timezone |
| Trigger slot | Уникальный номинальный момент планового расписания; не зависит от фактической задержки доставки trigger |
| Run | Одна зарегистрированная реакция на scheduled или manual trigger с собственным `run_id` и итогом |
| Processing run | Run, который получил единственное право выполнять общий pipeline |
| Daily cycle | Сохраняемый discovery-прогресс одного business day |
| Daily candidate | Уникальная пара `(business_day, game_key)` и её состояние обработки в этот день |
| Core data | Валидные основные данные, после атомарного сохранения которых игра считается обработанной сегодня по `ASM-04` |
| Enrichment | Отдельная retryable-работа, включая AI-резюме; её сбой не отменяет core success |
| Game key | `metacritic:game:<source_game_id>` по ID-first contract `SPK-03`; ID хранится как непрозрачная строка |
| Cursor | Следующая ещё не подтверждённо просмотренная позиция/страница SEE ALL в текущем daily cycle |

## Правила времени

1. Бизнес-логика получает время через управляемый `Clock`; тесты не читают системное время напрямую.
2. Scheduled trigger имеет уникальный ключ `(schedule_id, nominal_instant_utc)`. Повторная доставка того же ключа не создаёт новую работу.
3. После получения execution lease run один раз вычисляет `business_day` из фактического `started_at` и business timezone. Это значение неизменно до конца run.
4. Run, начавшийся до полуночи и завершившийся после неё, продолжает записывать дневной прогресс даты старта. Он не сбрасывает состояние посередине партии.
5. Первый processing run, начавшийся после границы суток, создаёт новый daily cycle. Старые daily cycles и накопленные игры не удаляются.
6. Manual trigger при включённом Bonus использует время получения execution lease и тот же pipeline. Он не заменяет scheduled trigger и не имеет отдельной модели прогресса.
7. Trigger slot хранится как UTC instant, поэтому повторяющийся или пропущенный локальный час при DST не создаёт одинаковые ключи. Business day всё равно вычисляется в выбранной зоне.

## Минимальное сохраняемое логическое состояние

Это перечень обязанностей состояния, а не проект физической схемы.

| Объект | Минимальные данные | Назначение |
|---|---|---|
| Run | `run_id`, trigger kind/key, `started_at`, business day, status, reason, итоговые counters | Дедупликация trigger и доказуемый результат каждого запуска |
| Execution lease | owner `run_id`, version/fencing token, expiry | Не более одного processing run; безопасное восстановление после падения |
| Daily cycle | business day, phase, SEE ALL cursor, exhaustion flag | Выбор New Releases ровно в начале дня и монотонное продвижение по SEE ALL |
| Daily candidate | business day, game key, source/rank, state, attempt metadata, last error | Определение «обработана сегодня», уникальность и retry |
| Item attempt | attempt ID, candidate, owner run/fencing token, start/end, outcome | Различение попытки, успеха и сбоя без удвоения counters |
| Game | game key и последнее валидное подтверждённое core state | Create/update одной игры без удаления между днями |
| Enrichment state | game key, input/version fingerprint, state, last error | Независимый retry AI без возврата core data в failed |

### Обязательные инварианты

| ID | Инвариант |
|---|---|
| `PS-INV-01` | Для одного scheduled trigger key существует не более одного Run; повтор возвращает существующий результат и не создаёт работу |
| `PS-INV-02` | В каждый момент только один Run владеет действующим execution lease; stale owner не может commit после смены fencing token |
| `PS-INV-03` | Для `(business_day, game_key)` существует один Daily candidate независимо от числа страниц, runs и attempts |
| `PS-INV-04` | Один processing run фиксирует не более 20 уникальных core candidates; retry входит в этот лимит |
| `PS-INV-05` | Core failure в текущем run не заменяется новым кандидатом в этом же run |
| `PS-INV-06` | Game upsert и переход Daily candidate в `processed` происходят атомарно; нет processed-маркера без сохранённых core data |
| `PS-INV-07` | SEE ALL cursor продвигается только вместе с сохранением всех обнаруженных identities просмотренного сегмента; ошибка не перескакивает непроверенный сегмент |
| `PS-INV-08` | Смена business day создаёт новый Daily cycle, но не удаляет Game или Enrichment state |
| `PS-INV-09` | Enrichment failure не меняет Daily candidate из `processed` обратно в core failure |
| `PS-INV-10` | Counters выводятся из уникальных terminal outcomes, а не увеличиваются повторной доставкой события |

## Состояния и переходы

### Run

Допустимые состояния: `queued`, `running`, `succeeded`, `partial`, `failed`, `skipped_duplicate`, `skipped_overlap`.

| Событие / условие | До | После | Запись состояния |
|---|---|---|---|
| Новый уникальный trigger, lease свободен | отсутствует | `queued` → `running` | Создать Run, получить lease/fencing token, зафиксировать `started_at` и business day |
| Повтор того же scheduled trigger key | terminal или active Run существует | `skipped_duplicate` как outcome запроса; исходный Run не меняется | Вернуть ссылку на исходный `run_id`, не создавать batch/items |
| Новый scheduled/manual trigger при занятом lease | отсутствует | `skipped_overlap` | Создать диагностическую запись trigger без processing work |
| Все выбранные core items успешны, enrichment не failed | `running` | `succeeded` | Зафиксировать terminal counters; нулевая партия при exhaustion также success |
| Есть подтверждённый progress и хотя бы одна core/enrichment error | `running` | `partial` | Успехи остаются; failed work получает retryable state |
| Progress отсутствует из-за execution/source failure или все core items failed | `running` | `failed` | Причина обязательна; claims переводятся в retryable после recovery |
| Процесс потерян и lease истёк | `running` | `failed` | Recovery закрывает Run причиной `interrupted/lease_expired`; stale fencing token отклоняется |

`skipped_duplicate` может быть HTTP/API outcome без отдельной строки Run, если существующий `run_id` возвращается вызывающей стороне. Наблюдаемое требование одно: новой processing work нет.

### Daily cycle

Допустимые фазы: `new_releases_pending`, `browse`, `exhausted`.

| Событие / условие | До | После | Правило |
|---|---|---|---|
| Первый processing run business day | daily cycle отсутствует | `new_releases_pending` | Создать цикл; накопленные Game не менять |
| New Releases успешно прочитан | `new_releases_pending` | `browse` | Атомарно сохранить до 20 уникальных Daily candidates в исходном порядке и закрыть initial selection |
| В New Releases меньше 20 позиций | `new_releases_pending` | `browse` | Не добирать SEE ALL в этом run по `ASM-06` |
| SEE ALL segment успешно просмотрен | `browse` | `browse` | Сохранить новые identities и следующий cursor одной транзакцией/checkpoint |
| SEE ALL segment завершился ошибкой | `browse` | `browse` | Cursor остаётся на ошибочном segment; уже подтверждённый предыдущий checkpoint сохраняется |
| Источник подтвердил отсутствие следующей позиции | `browse` | `exhausted` | Поставить exhaustion flag; не возвращаться в начало до нового дня |
| Наступил другой business day | любая фаза старого цикла | новый `new_releases_pending` | Старый цикл остаётся историей; сбросом является создание новой дневной области |

### Daily candidate и core attempt

Допустимые состояния: `pending`, `processing`, `processed`, `retryable`.

| Событие / условие | До | После | Правило |
|---|---|---|---|
| Identity впервые выбрана в текущий день | отсутствует | `pending` | Уникальная вставка `(business_day, game_key)`; повторная identity только читается |
| Run получает item claim | `pending` или eligible `retryable` | `processing` | Создать новый attempt с fencing token |
| Core validation и save успешны | `processing` | `processed` | Атомарно upsert Game и закрыть candidate/attempt |
| Core fetch/validation/save failed | `processing` | `retryable` | Сохранить классифицированную ошибку; не добирать замену в текущий run |
| Claim потерян при restart/lease expiry | `processing` | `retryable` | Recovery проверяет fencing token и сохраняет interrupted outcome |
| Та же identity встречена повторно сегодня | любое существующее | без изменения | Не создавать второй candidate и не расходовать новую позицию batch |
| Та же identity встречена в новый день | Game существует, daily candidate новой даты отсутствует | `pending` новой даты | После success обновить существующий Game и не создавать дубль |

`processed` означает только успешный core commit в данном business day. Состояния `pending`, `processing` и `retryable` не считаются «обработано сегодня».

### Enrichment

Допустимые состояния: `pending`, `running`, `succeeded`, `insufficient_data`, `retryable`.

- Core success создаёт/обновляет Enrichment state по fingerprint входа и версии AI-контура.
- Enrichment retry не входит в лимит 20 core candidates и не меняет дневной cursor.
- Ошибка переводит только enrichment в `retryable`; Run становится `partial`, а Daily candidate остаётся `processed`.
- Неизменный успешный fingerprint не запускается повторно; изменённый вход/версия создаёт новую попытку.

## Детерминированное формирование партии

При наличии execution lease Run выполняет шаги в следующем порядке:

1. Recovery переводит stale `processing` items в `retryable` и закрывает потерянные runs.
2. В batch по порядку первоначального выбора добавляются `pending` и eligible `retryable` candidates текущего business day.
3. Оставшаяся ёмкость равна `20 - selected_count`.
4. Если daily phase — `new_releases_pending`, сохраняются до 20 New Releases, фаза меняется на `browse`, а SEE ALL в этом run не читается даже при свободной ёмкости.
5. Если daily phase — `browse`, SEE ALL сканируется от сохранённого cursor. Уже существующие Daily candidates пропускаются; новые уникальные identities сохраняются в source order до заполнения ёмкости или exhaustion.
6. Если page/segment fetch падает, cursor не продвигается через ошибку. Уже выбранные элементы можно обработать, но Run заканчивается `partial` либо `failed` согласно фактическому progress.
7. Состав batch замораживается до core processing. Ошибка item не вызывает добор замены в том же run.
8. `exhausted` без pending/retryable work даёт успешный Run с нулём новых кандидатов и явными нулевыми counters.

Retry имеет приоритет над новым discovery, использует стабильный порядок первого выбора и выполняется не чаще одного раза для candidate в одном run. Конкретные backoff/max-attempt policy определяются позже, но item не может исчезнуть из retryable state молча.

## Бумажные сценарии с управляемым временем

Во всех сценариях business timezone — UTC, если не указано иное; `G01` и подобные обозначения — абстрактные game keys.

| ID | Given | When | Then |
|---|---|---|---|
| `PS-01` Первый запуск | 2026-09-04 09:00, daily cycle отсутствует, New Releases = `G01…G25` | Scheduled run получает lease | Создаётся цикл 2026-09-04; batch = `G01…G20`; SEE ALL не читается; после core success все 20 `processed`, phase = `browse` |
| `PS-02` Последующий запуск и страницы | Тот же день, `G01…G20` processed; SEE ALL page 1 = `G15…G25`, page 2 = `G26…G40` | Run в 10:00 формирует batch | `G15…G20` пропущены; batch = `G21…G40` в source order; ровно 20 unique; cursor указывает после page 2 |
| `PS-03` Ошибка item и retry | Batch `G41…G60`; `G47` падает, остальные успешны | Run завершается, затем начинается следующий | Первый Run = `partial`, 19 processed, `G47` retryable, без замены; следующий batch начинается с `G47` и добирает не более 19 новых; новый attempt может завершить её |
| `PS-04` Новый день и update | 2026-09-05 00:05; Game `G01` уже существует, daily cycle новой даты отсутствует; New Releases = `G01,G61` | Run получает lease и успешно сохраняет обе игры | Создаётся новый cycle; `G01` обновляется без дубля, `G61` создаётся; обе имеют отдельные processed-маркеры новой даты; старый cycle сохранён |
| `PS-05` Пересечение полуночи | Run получил lease 2026-09-04 23:59 и заканчивает в 00:03 | Items commit после полуночи | Все относятся к business day 2026-09-04; смены source посередине нет; следующий processing run создаёт cycle 2026-09-05 |
| `PS-06` Scheduled/manual overlap | Scheduled Run `S1` владеет lease; manual trigger `M1` приходит через секунду | `M1` пытается войти в pipeline | `M1` получает `skipped_overlap`; batch и item attempts не создаются; `S1` остаётся единственным владельцем |
| `PS-07` Повтор trigger | Scheduled trigger key уже связан с `S1` | Тот же trigger доставлен повторно | Возвращается `S1`/`skipped_duplicate`; новая работа и counters не появляются |
| `PS-08` Restart посередине | Batch и cursor сохранены; часть items processed, `G72` = processing; процесс падает до её atomic core commit | Fake clock проходит lease expiry, сервис стартует | Старый Run закрывается `failed`/interrupted; `G72` становится retryable; успехи остаются; cursor не откатывается и не перескакивает; stale commit отклонён |
| `PS-09` Ошибка следующей страницы | SEE ALL page 3 дала 8 новых identities и checkpoint; page 4 вернула timeout | Run продолжает доступную работу | 8 items можно обработать; cursor остаётся на page 4; Run = `partial` при успехах; следующий discovery повторяет page 4 |
| `PS-10` Исчерпание | Phase = `exhausted`, pending/retryable work нет | Следующий scheduled Run получает lease | Run = `succeeded`, selected/processed = 0; source не обходится заново до нового business day |
| `PS-11` AI failure | Core save `G80` успешен, AI timeout | Run завершается и позже выполняется retry | Daily candidate `G80` = processed; enrichment = retryable; Run = partial; AI retry не расходует позицию следующего core batch |
| `PS-12` Граница зоны | Business timezone = `Asia/Novosibirsk`; fake clock меняется с `2026-09-04T23:59:59+07:00` на `2026-09-05T00:00:00+07:00` | Два последовательных processing runs получают lease по разные стороны границы | Runs получают разные business day; второй начинает `new_releases_pending`; Game state не удаляется |

## Трассировка будущих тестов

| Requirement / risk | Правила и сценарии | Будущий автоматический evidence |
|---|---|---|
| `RUN-01`, `AC-RUN-01`, `ASM-02` | `PS-INV-01–PS-INV-02`, `PS-06–PS-07` | Fake scheduler test двух slots, duplicate delivery и overlap |
| `SEL-01`, `AC-SEL-01`, `ASM-03`, `ASM-06` | `PS-INV-04–PS-INV-05`, `PS-01` | Selector unit/integration test первого run |
| `SEL-02`, `AC-SEL-02`, `AC-SEL-03`, `AC-SEL-04`, `AC-SEL-06`, `ASM-05`, `ASM-07–ASM-08` | `PS-INV-03–PS-INV-07`, `PS-02–PS-03`, `PS-09–PS-10` | Multi-page, retry, failure и exhaustion tests |
| `SEL-03`, `AC-SEL-05`, `ASM-01`, `ASM-09` | `PS-INV-08`, `PS-04–PS-05`, `PS-12` | Fake-clock boundary test с state before/after |
| `DATA-01`, `AC-DATA-01–AC-DATA-02` | `PS-INV-03`, `PS-INV-06`, `PS-04`, `PS-07–PS-08` | Atomic upsert/idempotency integration tests |
| `NFR-01–NFR-02`, `AC-NFR-01–AC-NFR-02`, `ASM-04`, `ASM-22` | `PS-INV-06–PS-INV-09`, `PS-03`, `PS-08–PS-11` | Restart/fault-injection tests |
| `NFR-03`, `AC-NFR-03`, Bonus `OPS-02`, `AC-OPS-03` | `PS-INV-01–PS-INV-03`, `PS-06–PS-08` | Controlled concurrency barrier + trigger idempotency tests |
| `R-TIM-01` | `PS-01–PS-05`, `PS-09–PS-10`, `PS-12` | State-table regression suite |
| `R-TIM-02` | `PS-06–PS-08` | Persistence, lease expiry, fencing и concurrency tests |

## Ограничения и остаточные риски

- `SPK-02` подтвердил фактическую пагинацию, порядок и наблюдаемый признак дальнейших страниц; Cursor остаётся абстрактным checkpoint до выбора persistence stack.
- `SPK-03` определил `game_key`, aliases и platform identity; реализация обязана отклонять missing/conflicting source ID до изменения core data.
- `SPK-06` должен подтвердить, что выбранная среда поддерживает persistent state, scheduled trigger, atomic ownership и нужную точность времени.
- Изменение порядка live source между запросами может привести к пропуску вставленной перед cursor игры; дневной identity set устраняет дубли, но не гарантирует snapshot внешнего списка.
- Точные retry backoff, maximum attempts, lease TTL и recovery interval выбираются после стека; они не могут ослаблять инварианты этой модели.
- `ASM-01–ASM-09` остаются явно provisional там, где автор задания не дал уточнение. `SPK-04` доказал внутреннюю непротиворечивость, а не авторство этих трактовок.

## Проверка критерия выхода

- [x] Первый run, последующий run и новый business day имеют единственный источник и переход.
- [x] Лимит 20, retry и запрет добора после item failure заданы однозначно.
- [x] Core progress и enrichment разделены.
- [x] Restart восстанавливается только из persistent state без доверия памяти процесса.
- [x] Duplicate trigger, scheduled/manual overlap и stale owner не создают двойную работу.
- [x] Page failure и exhaustion не перескакивают и не зацикливают cursor.
- [x] Все календарные сценарии методологии сопоставлены с Given/When/Then и будущим test evidence.
- [x] Результаты `SPK-02–SPK-03` встроены в cursor/identity модель; `SPK-06` сохранён как ограничение, а не подменён догадкой.

**Вывод:** состояния и переходы достаточно однозначны для test-first реализации. `R-TIM-01` и `R-TIM-02` переходят из исследования в митигацию и остаются открыты до автоматических failure/concurrency tests.
