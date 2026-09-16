# BON-00: выбор и проработка плана Bonus 2

Дата review: 2026-09-16. Основание: запрос владельца проработать бонусный план
с уточнением «вторая часть»; исходный code baseline `ce777b9`.
Текущие статусы и зависимости — только в [action_plan.md](../../action_plan.md).

## Exit criteria и основания

| Критерий решения | Независимое основание / проверка | Граница вывода |
|---|---|---|
| Scope определён после G6 | Уточнение владельца в сессии; прежние [PUB-01](pub_01_review.md), [PUB-02](pub_02_review.md), [PUB-03](pub_03_review.md) | [ADR-0002](../decisions/0002-bonus2-scope.md) записывает решение, но не является доказательством работоспособности Bonus |
| Обе функции Bonus 2 покрыты | [assignment.md](../../assignment.md), `OPS-01/02` и `AC-OPS-01/02/03` сопоставлены с [BON-21/22](../../implementation_plan.md#bon-21) | YouTube исключён из выбранной ветки; Must не исключены |
| Оценка учитывает реальные пробелы | [settings](../../app/config/settings.py), [selector](../../app/processing/selector.py), [scheduler](../../app/processing/scheduler.py), [provisioning](../../scripts/provision_db.py) | 32 ч + 8 ч резерва — оценка, не измеренная скорость; deadline/capacity неизвестны по принятому `CTX-01/02` |
| Поставка и резерв сохранены | Неизменные `REL-*` estimates дают 16 ч; отдельные 4 ч резерва поставки | Календарные ожидания не включены; ресурсные ограничения явно записаны в ADR |
| План не обходит зависимости | Offline audit и negative controls, команды ниже | Проверяют структуру/арифметику, не runtime correctness |
| Substantive технические решения не приняты без tests | [Проект контракта](../bonus2_design.md) отмечен Candidate; будущая evidence-матрица ссылается на DB/clock/browser oracles | Ни freshness, ни auth/grants, ни manual execution пока не верифицированы |

## Adversarial self-review

Проверены требования, AC, risks, counterexamples, границы и отсутствующее
evidence. Отдельный агент не запускался; ниже результат собственного review
плана, а не независимый code review ещё не написанной реализации.

| Найденный пробел первоначального предложения | Исправление плана |
|---|---|
| Показ существующих run counters давал бы нулевой прогресс до финала | Live CoreAttempt projection; согласовать terminal/recovery counts и persistent batch membership до UI |
| Heartbeat между tick пропадает при нормальном долгом HTTP; отдельный heartbeat может скрыть зависание | Heartbeat вне blocking call; отдельно last_progress/operation deadline; stale не отзывает lease |
| Последовательный manual batch способен задержать часовой timer | Отделить scheduled intent registration от core execution; тест перехода часа и отдельного scheduled key |
| Разные request keys/операторы обходят защиту от double click | Атомарные global busy/cooldown/rolling limit, constraint и PostgreSQL barrier tests |
| Применение существующих ALL TABLES grants к auth даёт background roles лишние права | Явная role allowlist после migrations, запрет auth/session DML фоновым ролям, negative SQL tests |
| Web SELECT-only несовместим с sessions, last_login и command admission | Явная ограниченная миграция grants; учесть password-hash upgrade, не выдавать общий UPDATE на пользователей |
| Общая lease-блокировка в HTTP требовала бы write privilege на продуктовую таблицу | Отдельная TriggerAdmission singleton; web и scheduler используют единый порядок блокировок, web lease только читает |
| Recovery может сменить состав партии и нарушить смысл counters/лимит | Зафиксировать membership до HTTP, общий бюджет и одинаковый oracle для live/terminal counts |
| Draft design и будущие tests могли выглядеть как принятое решение | Accepted только scope ADR; контракт Candidate, runtime задачи требуют отдельных CI/public artifacts |

Оставшиеся ограничения: performance/freshness и UI ещё не измерены; auth и
shared dispatcher предстоит реализовать; live SSH/operator capability проверяется
при публичных срезах. Наличие прошлых VDS checks не доказывает текущий доступ.
Это явный scope будущих задач, не основание принимать их заранее.

## Проверка planning-изменения

Выполнено локально на planning diff:

```powershell
.\.venv-app\Scripts\python.exe -B research/planning/check_plan.py
.\.venv-app\Scripts\python.exe -B -m unittest discover -s research/planning -p "test_*.py"
git diff --check
```

`check_plan.py` прошёл: 46 tasks, 9 gates, 28 Must, 3 Bonus, 47 AC, 24 risks;
scope `bonus2`, оценка полного графа 177 ч (исторический base 145 + Bonus 32),
цепочка зависимостей 135 ч. Все **18 negative-control tests** прошли.
`git diff --check` прошёл.

Дополнительная проверка прошла: 245 локальных Markdown links/anchors в 9
изменённых файлах разрешаются, файлы имеют LF/UTF-8 без BOM.
`test_check_plan.py` адаптирован к уже выбранному scope вместо жёстко
зашитого `pending`: проверки всех четырёх ветвей и отклонения непринятого scope
сохраняются. Application suite, deploy и live calls не нужны для этого
planning-only diff и не заявляются выполненными.
