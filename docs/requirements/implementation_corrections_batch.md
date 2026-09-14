# Серия исправлений аудита — 2026-09-14

Пользователь разрешил выполнить всю оставшуюся очередь из
[аудита `6551e42`](implementation_audit_6551e42.md#очередь-исправлений).
Каждый блок проходит author → adversarial self-review → verification → focused
commit; серия продолжается без отдельного подтверждения следующего блока.
Текущие статусы и число открытых findings — только в
[action_plan.md](../../action_plan.md). Hosted CI/public gates, similarity и Bonus
не входят в эту серию. Исторические defect probes не изменяются.

## IMP-03: R16/R20 — core ownership и retry budget

Связь: `NFR-02/03/04`, `AC-NFR-03`, `R-TIM-01/02`. Проверка owner/token/expiry
теперь предшествует claim, recovery и сохранению ответа. Candidate перечитывается
под row lock; повторный вызов не переоткрывает processing/processed/failed.
Начало CoreAttempt и счётчик сохраняются до HTTP. Прерванные попытки закрываются
следующим владельцем; пятая ошибка или crash исчерпывает дневной бюджет.
State/counter edits не обходят историю attempts. Failed rows не занимают batch.

Независимое evidence — [test_processing_ownership.py](../../app/tests/test_processing_ownership.py):
7 regressions покрывают stale owner до HTTP/после ответа/при recovery, expiry
без reclaim, повтор завершённого claim, 20 постоянно ошибочных игр с продвижением
21-й и пять crash/restart циклов. Первоначальный запуск воспроизвёл дефекты
(3 failures, 3 errors). Старые multi-run fixtures теперь явно меняют FakeClock
между runs: прежняя зависимость от числа вызовов часов случайно переносила первый
run за пределы его 45-минутной аренды. Midnight crossing остаётся отдельным test.

Adversarial review проверил границы транзакций, stale in-memory candidate,
доставку старого ответа после нового успешного commit и сброс счётчика при reopen.
Начатая попытка расходует бюджет даже при неизвестном результате HTTP; это
сохраняет bounded recovery без удаления истории. Старые counts выше пяти
сохраняются, новые automatic attempts по ним не запускаются. Новый business day
даёт новый candidate; отдельной команды сброса дневного бюджета нет.

Проверка: полный `python -B scripts/check.py` в `.venv-app`, PostgreSQL 16;
205 application tests, format/lint/mypy/migration drift, scripts 6, planning 18,
AI 7, selection 9 tests и frozen/candidate verifiers — PASS, exit 0.
Изолированные тесты и документация
не являются доказательством hosted CI, production throughput или VDS recovery.

## IMP-02/03: R19 — source validation и изоляция партии

Связь: `DATA-02/03`, `NFR-02/04/05`, `AC-NFR-02/04/05`, `R-EXT-04`.
Parser проверяет тип/диапазон Metascore и finite Userscore в 0–10 с точностью
хранимого decimal поля. Отсутствующая оценка сохраняется как отсутствие, а
некорректный числовой label классифицируется как invalid. Общий DTO validator
проверяет размеры и типы строк, NUL, media URL и platform identity duplicates
до upsert. Неверный основной DTO получает invalid source evidence; candidate
становится retryable/failed по общему лимиту, следующая игра партии продолжается.
Неверная отдельная platform Userscore сохраняет прежнее хорошее значение и
собственное invalid evidence, разрешая обновить остальные валидные поля.

Независимое evidence — [test_source_validation.py](../../app/tests/test_source_validation.py),
7 tests: -1/101/bool/string/float Metascore, некорректные Userscore labels,
NaN/выход за диапазон/лишняя точность, переполнение title, границы 0/100/10 и null,
сохранение старых данных, продолжение второй игры и unexpected exception.
Первые пять tests были выполнены до исправления и воспроизвели ошибки.
Frozen batch size теперь сохраняется до обработки; unexpected exception закрывает
свои открытые attempts/candidates и run с точными counters и `unexpected_error`,
освобождает lease, затем выходит наружу. Это не скрывает программную ошибку;
ожидаемые ошибки источника обрабатываются отдельно и не прерывают batch.

Adversarial self-review проверил null против zero, Decimal finite/precision,
частичный secondary fetch, rollback good values, полный batch selection против
числа начатых attempts и запрет recovery чужого owner при неожиданной ошибке.
Полный local `scripts/check.py`: 212 application tests, format/lint/mypy/drift,
scripts 6, planning 18, AI 7, selection 9 и frozen/candidate verifiers — PASS,
exit 0. Live contract текущего Metacritic и hosted CI этим не заявляются.

## IMP-04: R01/R09/R10 — измеренный запрос, квота и попытки

Связь: `AI-01/02/03`, `NFR-02/03`, `R-AI-01/02`, `R-TIM-02`.
Preflight считает canonical messages + schema фактически отправляемого payload,
добавляет 64 framing tokens и резервирует ещё 800 completion tokens. Prompt выше
6000 или недоступный tokenizer закрывают job без HTTP. Hash, raw/guarded tokens,
версии и fencing token сохраняются до HTTP; adapter отправляет те же bytes.
Старые corpus estimates не используются для admission. Новые corpus diagnostics
учитывают полный запрос; превышение лимита не откатывает уже собранную страницу.

PostgreSQL transaction advisory lock сериализует проверку и создание reservation.
Ledger учитывает token и request limits в rolling minute/day windows, открытые и
прерванные attempts. Allowlisted provider headers могут отложить следующий вызов;
без достоверных headers он ждёт минуту. Превышение фактического usage останавливает
данный contour. Ограничения относятся к одному provider account в этой БД;
потребление его ключа другими приложениями требует актуальных provider headers.

Внутренние HTTP retries удалены: один вызов соответствует одной durable attempt.
Пять попыток исчерпывают automatic budget; recovery закрывает незавершённую как
abandoned. State/token/expiry проверяются до admission и после HTTP; redelivery
и поздний ответ не переписывают terminal history. HTTP выполняется вне DB locks,
с timeout 180 секунд на I/O phase и lease 5 минут; это не обещание общего
wall-clock deadline для произвольно медленного streaming response.

Evidence — [test_summary_admission.py](../../app/tests/test_summary_admission.py):
16 regressions, включая десять multilingual inputs по 450 tokens, actual wire
hash, две реальные DB connections, minute/day/request limits, headers, NaN,
crash/reclaim/late response, пять ошибок и usage overrun. Начальные девять tests
дали 6 failures и 2 errors до исправлений. Adversarial self-review дополнительно
проверил отсутствие DB locks при HTTP и неизменность выигравшего результата.
Общий application suite: 228 tests PASS; format/lint/mypy/drift и scripts 6 PASS.
При общей проверке обнаружена неверная постановка IMP-02/03 в In progress при
незакрытых prerequisites; tracker сохраняет Changes requested до полного evidence,
отдельно указывая проверенные локальные corrections. Offline checks повторены
после этой правки. Prompt/schema и frozen quality/selection oracles не менялись.

Migration `summaries.0003` добавляет attempt metadata. Исторические unknown fields
остаются пустыми; adapter version 1.1.0 и tokenizer package version входят в новый
contour, старые pending jobs получают contour_changed без вызова API. Новое
обычное построение corpus создаёт job для текущего contour. Production database
этой серией не мигрировалась; hosted/live throughput здесь не проверен.

## IMP-04: R07/R13/R18 — grounding и фактический input

Связь: `AI-01/02`, `ASM-16/17/19`, audit R07/R13/R18.
Canonical validator проверяет тип status до membership, формат support и его
принадлежность именно отправленному набору IDs. Adapter и worker проверяют
grounding перед публикацией; один неверный claim отклоняет весь output, без
частичной записи и без молчаливого пропуска support. Неверные JSON field types
дают классифицированную malformed_output attempt, не незавершённый running job.
Порог three reviews применяется к фактическим corpus items после frozen dedup;
недостаточный input создаёт rule insufficient_data без reservation/HTTP.

Evidence — [test_summary_validation.py](../../app/tests/test_summary_validation.py):
6 tests с malformed type matrix, неизвестным R10, валидным R01, защитой worker
при неверной отметке adapter и реальным collector → corpus → worker для трёх
дубликатов. До исправлений получены failures/errors; исправленная sparse fixture
отдельно подтвердила нежелательный вызов adapter. Adversarial self-review проверил
атомарное отклонение смешанного valid/invalid output и сохранение исходных claims.
Adapter version 1.2.0 меняет contour; prompt/schema и selection oracle неизменны.
Local suite: 234 application tests, format/lint/mypy/drift, scripts 6, planning 18,
AI 7, selection 9 и frozen/candidate checks PASS. Семантическое соответствие claim
тексту отзыва остаётся качеством frozen AI evaluation; ID check его не доказывает.

## IMP-04: R08/R11 — повтор страницы и durable SourceFetch

Связь: `NFR-02/03`, `R-TIM-02`, audit R08/R11. Лимит пяти попыток теперь
считается по ledger текущей generation/page; успешное продвижение курсора даёт
следующей странице собственный бюджет. Общий attempt_count остаётся числом всех
HTTP intents, включая успешные страницы. Backoff также считается для текущей
страницы. Пять crashes не обходят лимит: reclaim закрывает started как abandoned.

Перед HTTP под Game → job locks проверяются state/token/expiry/generation/cursor/
page и отсутствие открытой попытки этого claim. SourceFetch started и attempt
counter коммитятся до вызова; URL строится той же функцией, что в gateway.
После ответа повторная проверка допускает единственный terminal transition.
Старый ответ закрывает ещё открытую попытку как superseded; abandoned/terminal
history не переписывается. Ошибочная страница получает invalid и не занимает
unique key принятой страницы. Cursor, observations, corpus и summary intent
сохраняются одной транзакцией; при handoff rollback durable started остаётся.

Evidence — [test_collection_attempts.py](../../app/tests/test_collection_attempts.py):
9 tests, первые 8 до исправления дали 7 failures и 1 error. Проверены шесть
успешных страниц + retry, reset бюджета после четырёх ошибок, terminal/in-flight
redelivery, expiry, пять crashes, late response после победившего нового owner,
смена generation/cursor и видимость started из другой DB connection вне atomic
HTTP. Два прежних crash tests уточнены: уже начатый HTTP оставляет evidence,
при этом observations/corpus/summary по незафиксированной странице отсутствуют.
Adversarial self-review проверил порядок locks и failed/invalid page uniqueness.
Local full suite: 243 application tests и все format/lint/mypy/drift/offline checks
PASS. Migration `catalog.0005` расширяет choices без изменения исторических строк.
Generation restart после unstable/failed остаётся отдельной recovery операцией;
новая серия не сбрасывает исторические budgets и не ремонтирует старые snapshots.
