# G3: проверка implementation baseline

Задача: `PLN-03`. Дата: 2026-09-09 (Asia/Novosibirsk). Review: adversarial self-review с независимыми реестрами и исполняемыми negative controls; отдельный человек-рецензент не участвовал.

Решение по результатам проверки: **Accepted implementation baseline**. Проверяется готовность плана, не выполнение будущих задач приложения. Текущие task/gate статусы ведутся в master tracker.

## Источники и граница изменения

- Исходник: [assignment.md](../../assignment.md), SHA-256 `C8987F684CFDF693AB188FA2AC5875044C93EBF486B708C36FDF7E7748C2125C`.
- Независимые основания покрытия: [реестр требований](requirements.md), [47 acceptance scenarios](acceptance.md), [допущения](assumptions.md), [реестр рисков](../risks.md).
- Принятые основания реализации: [ADR-0001](../decisions/0001-minimal-stack-and-architecture.md), [design](../design.md), [PLN-02 review](pln_02_review.md), результаты Must-spikes из [G2](g2_review.md).
- Проверяемые результаты: [master tracker](../../action_plan.md), [implementation backlog](../../implementation_plan.md), [offline audit](../../research/planning/check_plan.py) и его [negative controls](../../research/planning/test_check_plan.py).

Предыдущий baseline сохранён в `git show 0c353ec:action_plan.md`. Все 46 Task IDs сохранены; исторические decisions/evidence не удалены. Перенос описаний и оценок не меняет исходник, Given/When/Then, принятые architecture/data contracts или статус quality candidates.

## Exit criteria и независимое evidence

| Критерий PLN-03 / G3 | Проверка и результат | Граница вывода |
|---|---|---|
| Каждый Must имеет реализацию и проверку | Audit сравнил обе колонки mappings с реестром: 28 Must и 3 Bonus; acceptance ссылается на те же 31 requirement IDs | Это структурная полнота назначений, не прохождение 47 сценариев |
| Критические риски не потеряны | Сверка risk headings и mappings: 24/24, Must не зависит от Bonus; ручной review подтвердил capacity/storage, public preflight, recovery, archive и quality checks | Риски не закрыты наличием плана; R-PLN-01 остаётся Open — mitigate |
| Стек обоснован | Принятый ADR связывает компоненты с потребностями и подтверждённой средой; PLN-02 отделяет проверенный design от будущего runtime | Новый стек или платные обязательства не приняты; canonical Python 3.12/Django runtime ещё предстоит создать |
| Ранний публичный вертикальный срез | Граф ставит IMP-01/IMP-02 перед остальными функциями; сумма их подзадач — 20 ч. Early endpoint и реальная карточка имеют отдельные exit checks | При рекомендуемой ранней подготовке двух oracles перед карточкой добавляется 8 ч работы; внешнее ожидание не оценено календарно |
| Fixtures/evals/failure/docs/deploy выделены | У 29 будущих задач есть результат/проверка и численная декомпозиция. Parser fixtures явно предшествуют parser в IMP-02/IMP-04; отдельные eval-, HRD-, PUB-, REL-задачи | Существующие curated observations не объявлены parser inputs; test artifacts будут созданы соответствующими задачами |
| Bonus только после обязательной готовности | Все четыре графа none/bonus1/bonus2/both ацикличны; BON-* имеют предка G6, REL-* — GB; none не ждёт невыбранные ветки | BON-00 ещё не выбирал scope. Product/public readiness G6 не подменяет финальную сдачу G7 |
| Резерв и бюджет видимы | Audit суммировал подзадачи: base 145 ч, округлённые 25% = 37 ч, всего 182 ч; резерв разделён между интеграцией, внешним drift, public recovery и сдачей | Это инженерные оценки, не измеренная скорость. Дедлайн/ёмкость неизвестны; соответствие календарному бюджету **не доказано**, как допускал предыдущий PLN-03 baseline |
| Критический путь и порядок не противоречат выходам | Audit проверил gate ancestry, полноту пути к G7 и обязательный порядок oracle → method, IMP-03 → IMP-04, README/archive → final freeze | Longest dependency chain — нижняя граница гипотетически параллельного графа, не план ускорения одного исполнителя |
| Один source of truth | Текущие статусы/зависимости/evidence находятся только в action_plan; scope, task descriptions, оценки и mappings — только в implementation_plan; README/AGENTS/methodology согласованы | Исторические review содержат датированные решения, а не конкурирующий текущий tracker |

Поведенческие допущения дополнительно сопоставлены существующим task checks: UTC/день/выборка → IMP-03/HRD-02; identity/null/partial → IMP-02/HRD-01–HRD-03; language/selection → REV-EVAL-01/IMP-04; UI → IMP-05/IMP-07; similarity → SIM-EVAL-01/IMP-06/SIM-VER-01; архив/доступ → REL-*; Bonus assumptions → условные BON-*.

## Найденные противоречия и исправления

| Finding | Контрпример | Исправление / проверка |
|---|---|---|
| High: прежний G6 требовал все Must, включая DEL-04 | Чтобы пройти G6, нужно отправить результат; чтобы начать REL-05, нужно уже пройти G6 | G6 требует продуктовую/эксплуатационную готовность, G7 — все 28 Must и подтверждение отправки. Ни один delivery AC не удалён |
| High: финальный кандидат проверялся до README/архива | Инструкции запуска меняются после clean-checkout проверки | REL-02/REL-03 предшествуют REL-01. Runtime/config/setup change переоткрывает затронутую приёмку; позднее дополнение архива проходит отдельный privacy/manifest check |
| Medium: не все HRD-зависимости явно выражали G4 | Исполнитель мог начать интеграционный hardening без полного functional slice | Все HRD-* стоят после G4; базовые failure tests остаются уже внутри IMP-* |
| Medium: AI-задача опиралась только на каталог | Durable daily candidates/ownership/recovery ещё не реализованы | IMP-04 теперь зависит от IMP-03 и принятого REV-EVAL-01; минимальный atomic core/job intent остаётся в IMP-02 |
| Medium: сокращение карточек могло потерять exit details | Только сумма часов и ссылка не гарантируют parser inputs до кода или проверку внешних similarity IDs | Сверены прежние task exit criteria; явно восстановлены порядок review fixtures, диагностический provenance, first/last-page/вне-sample контрпримеры и only-own-DB invariant |
| Medium: часы могли выглядеть как календарное обещание | Неизвестная ёмкость, ожидание owner/DNS/hourly windows/AI queue | Ожидание отделено, CTX-01/CTX-02 и R-PLN-01 синхронизированы; 20 ч двух срезов не выдаются за срок с учётом ранних oracles |

Неустранённых материальных замечаний к плану после этих исправлений не обнаружено. Это не означает отсутствия будущих ошибок реализации.

## Воспроизводимые проверки

Из корня репозитория, Python 3.12+ standard library, без `.env`, AI calls, Docker или сети:

```powershell
python -B research/planning/check_plan.py
python -B -m unittest discover -s research/planning -p "test_*.py" -v
git diff --check
Get-FileHash -Algorithm SHA256 assignment.md
```

Фактический запуск локальным `.venv/Scripts/python.exe` (исследовательский Python 3.14.7): audit прошёл, 12/12 tests прошли. Tests проверяют корректный baseline и 11 повреждений: отсутствующее Must/risk mapping, цикл, обход G4/G6, freeze до README, безусловный Bonus, неверная сумма подзадач, неизвестный task, duplicate task, Must через Bonus. Изменения для negative controls делаются только в памяти; рабочие документы не повреждаются.

Заключительная файловая проверка: `git diff --check` без замечаний; SHA-256 исходника совпал; `git diff --quiet` подтвердил отсутствие изменений assignment, requirements, acceptance, assumptions, ADR и design. PowerShell-проверка Markdown links в восьми затронутых документах разрешила 170 локальных ссылок, включая 63 anchors: отсутствующих целей нет. Git-история предыдущего плана сохранена; проверка не обращалась к внешним сайтам и не подтверждает доступность future application URL.

| Сценарий графа | Работа, ч | Самая длинная зависимая цепочка, ч |
|---|---:|---:|
| Без реализации Bonus | 145 | 103 |
| Bonus 1 | 165 | 123 |
| Bonus 2 | 159 | 117 |
| Оба Bonus | 179 | 123 |

Здесь нет резерва и календарного ожидания. Базовый резерв — 37 ч; Bonus требует отдельного пересмотра резерва после BON-00/BON-11. В базовой длиннейшей цепочке HRD-05 определяет join G5; REL-02 и REL-03 равны по 4 ч, любая из них может представлять этот участок пути. Для одного исполнителя применима сумма работы, а не только длина цепочки.

## Остаточные ограничения и следующий цикл

- Free AI quota не обеспечивает теоретический maximum changed-input stream; queue сама по себе не увеличивает throughput. Исполняемые workload scenarios → IMP-04/HRD-04, реальные arrivals/completions/backlog/oldest age → PUB-02, недренируемая нагрузка → R-AI-02 Replan.
- Глобальный максимум объёма отзывов и вместимость production storage не доказаны. Измерения text/observation/attempt/index/WAL/backup и headroom → HRD-05/PUB-02; удаление истории не разрешено этим планом.
- REV-EVAL-01/SIM-EVAL-01 потребуют конкретного owner acceptance после подготовки. До этого методы остаются Candidate. Docker/Compose/deploy access проверяется в IMP-01; недостающий доступ оформляется Ask к соответствующим воротам.
- Исходники приложения, CI, migrations, runtime tests и working public service этим циклом не созданы. Новый инфраструктурный расход, Bonus scope или отправка результата не разрешены автоматически.

PLN-03 и G3 проверены **только на уровне implementation baseline**. Следующая единственная приоритетная задача — IMP-01; начало реализации не входит в этот commit.
