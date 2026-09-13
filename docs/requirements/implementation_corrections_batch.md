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
