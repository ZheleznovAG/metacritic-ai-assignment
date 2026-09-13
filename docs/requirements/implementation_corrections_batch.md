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
