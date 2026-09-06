# `SPK-03` — идентичность игры и безопасное обновление

## Вопрос, граница и решение

**Вопрос:** какой внешний ключ отличает игру от платформенной версии, позволяет обновлять накопленную запись без дубля и не сливает разные игры при похожих названиях или URL-вариантах?

**Проверено:** 2026-09-06, 14:37–14:42 UTC.

**Граница:** локальная проверка SSR HTML Metacritic в ранее разрешённом владельцем scope; последовательные HTTPS GET без аутентификации, cookies и обхода защит, user-agent feasibility probe версии `0.3`. Полные ответы использовались только во временном каталоге. В Git сохранена [curated fixture](fixtures/metacritic/identity-cases.json) с идентификаторами, хешами и ожидаемыми решениями, но без стороннего HTML.

**Решение:** `Proceed with limitation`.

Первичная identity игры — пара `(source = metacritic, source_game_id)`, где `source_game_id` — непрозрачная строка из `game-title.id` встроенного SSR Nuxt payload. Canonical path, slug и title являются локаторами или изменяемыми атрибутами, но не ключом. Платформенный вариант — дочерняя сущность одной игры с ключом `(game_key, source_platform_id)` и сохранённым `source_game_platform_id = relatedGameId` как дополнительным внешним утверждением и детектором конфликтов.

Ограничение принципиально: найденные ID присутствуют в структурированном SSR payload, но не документированы как публичный стабильный API-контракт. Поэтому реализация обязана хранить aliases и provenance, а отсутствие или конфликт ID превращать в заметную retryable/conflict ошибку. Эвристическое слияние по title/slug запрещено.

Связи: `DATA-01`, `DATA-03`, `SEL-01–SEL-03`, `AC-DATA-01–AC-DATA-04`, `ASM-10–ASM-13`, `R-ID-01`, `R-DAT-01`.

## Наблюдаемый контракт

На текущей странице [SEE ALL / All New Games](https://www.metacritic.com/browse/game/all/all/all-time/new/) все 24 карточки имели `game-title.id`, title и slug в SSR payload. Для Water Margin Heroes ID `1300758826` совпал между списком и [detail page](https://www.metacritic.com/game/water-margin-heroes-eight-acts-of-battle/).

У [Elden Ring](https://www.metacritic.com/game/elden-ring/) ID `1300501979` совпал на detail page и [critic route для PC](https://www.metacritic.com/game/elden-ring/critic-reviews/?platform=pc). Одна game identity содержит пять связанных платформ. У каждой наблюдались:

- глобальный `source_platform_id` из platform object `id`;
- `source_game_platform_id` из `relatedGameId`;
- slug и отображаемое имя платформы;
- отдельные score/review данные по контракту `SPK-02`.

Название не является ключом. [Sonic the Hedgehog](https://www.metacritic.com/game/sonic-the-hedgehog/) имеет ID `1300003250`, а [Sonic the Hedgehog (2006)](https://www.metacritic.com/game/sonic-the-hedgehog-2006/) — `1300025436`; это две игры, несмотря на близкие человеческие названия. Аналогично редакционная граница Metacritic определяет editions/remasters: отдельный `game-title.id` означает отдельную Game, а не платформу исходной игры.

Запрос без завершающего `/` перенаправился на `/game/elden-ring/`. Query parameters и subroutes не образуют новую игру: связь принимается только после совпадения `source_game_id`. Это не разрешает механически обрезать произвольный URL до slug без проверки ID.

## Нормализация внешних значений

| Значение | Правило |
|---|---|
| `source_game_id` | Хранить как непустую непрозрачную decimal string; не вычислять и не выводить из URL |
| `game_key` | `metacritic:game:<source_game_id>`; это логический ключ, формат физического PK выбирается позже |
| Canonical locator | Только HTTPS host `www.metacritic.com` и canonical path `/game/<slug>/`; host приводится к lowercase, query/fragment не входят в alias |
| Title | HTML-decode, trim и collapse whitespace для отображения; никогда не участвует в identity match |
| `source_platform_id` | Непрозрачная строка из platform object `id`; имя и slug остаются изменяемыми атрибутами |
| `game_platform_key` | `(game_key, source_platform_id)` |
| `source_game_platform_id` | Непрозрачная строка из `relatedGameId`; обязана однозначно указывать на ту же пару game/platform |

ID не преобразуются в числа базы данных: строковое хранение не закладывает недоказанную разрядность или арифметическую семантику.

## Граница сущностей

```text
Game
  identity: source + source_game_id
  mutable: title, description, developer, media, current canonical locator
  aliases: historical/current canonical locators
  platforms:
    GamePlatform
      identity: Game + source_platform_id
      assertion: source_game_platform_id
      mutable: platform name/slug, Metascore, Userscore, review inputs
```

Один `game-title.id` всегда создаёт не более одной Game. Несколько platform objects этого ID создают несколько GamePlatform, но не несколько Game. Другая edition/remaster/reboot с собственным `game-title.id` — отдельная Game даже при совпадающем или очень близком title.

## Алгоритм разрешения и upsert

Identity разрешается до изменения business fields и в одной атомарной операции с регистрацией aliases.

1. Из list item извлечь `source_game_id`, canonical-looking path и provenance. Если ID отсутствует или имеет неверный тип, пометить item/page как `identity_unresolved`; не создавать кандидата по title/slug.
2. Найти Game по уникальной паре `(source, source_game_id)`.
3. Если Game найдена, проверить canonical locator. Новый свободный locator добавить как alias и сделать текущим; ранее известный оставить историческим.
4. Если Game не найдена, проверить locator. Свободный locator позволяет создать Game; locator, уже связанный с другим ID, даёт `identity_conflict` без merge и без изменения обеих записей.
5. После detail fetch повторно потребовать тот же `source_game_id`. Несовпадение list/detail — `identity_conflict`, core update запрещён.
6. Для каждой платформы upsert выполнить по `(game_key, source_platform_id)`. `source_game_platform_id` должен быть свободен или уже связан с этой же парой; иначе `platform_identity_conflict`.
7. Только после успешного identity check применить non-destructive merge `ASM-11`. Платформа, отсутствующая в частичном ответе, не удаляется: отсутствие не доказывает прекращение существования варианта.
8. Уникальная вставка `(business_day, game_key)` создаёт DailyCandidate. Повтор того же ID в New Releases/SEE ALL или на соседней странице только читает существующего кандидата и не расходует вторую позицию batch.

Логи обязаны содержать внутренний `game_id`, `source_game_id`, locator, решение `created/updated/skipped/conflict` и классифицированную причину без сохранения полного стороннего ответа.

## Минимальные уникальные ограничения

Конкретная схема остаётся задачей implementation baseline, но её наблюдаемые инварианты уже фиксированы:

| Область | Уникальность / проверка |
|---|---|
| Source game | `UNIQUE(source, source_game_id)` |
| Source alias | `UNIQUE(source, normalized_canonical_locator)` |
| Platform membership | `UNIQUE(game_id, source_platform_id)` |
| Platform assertion | `UNIQUE(source, source_game_platform_id)` и соответствие той же game/platform pair |
| Daily selection | `UNIQUE(business_day, game_id)` либо эквивалент по `game_key` |

Внешние ключи не заменяют внутренние surrogate IDs. Они определяют idempotency на границе источника; внутренние ID обеспечивают ссылки UI, reviews, summaries и similarity.

## Проверочные случаи

| Case | Вход | Ожидаемый результат |
|---|---|---|
| `ID-01` List → detail | Water Margin Heroes, ID `1300758826` в обоих ответах | Одна Game |
| `ID-02` Detail → review route | Elden Ring, ID `1300501979` на двух routes | Одна Game; route не создаёт запись |
| `ID-03` Multiplatform | Elden Ring и пять разных platform IDs/`relatedGameId` | Одна Game, пять GamePlatform |
| `ID-04` Similar title | Две страницы Sonic с разными IDs | Две Game; title match игнорируется |
| `ID-05` URL syntax | `/game/elden-ring`, canonical path и query/subroute | Одна Game только после совпадения ID |
| `ID-06` Mutable pagination | Шесть повторных paths из `SPK-02` | Не более одного DailyCandidate на `game_key` |
| `ID-07` Changed title | Известный ID, новое валидное title | Update существующей Game, count не меняется |
| `ID-08` Changed slug | Известный ID, новый свободный canonical locator | Та же Game, новый current alias, старый сохранён |
| `ID-09` Alias collision | Известный locator пришёл с другим ID | `identity_conflict`, ни insert, ни update |
| `ID-10` Missing ID | Новый title/path без `game-title.id` | `identity_unresolved`, retry; эвристического insert нет |
| `ID-11` Partial platforms | Известная Game, ответ не содержит ранее сохранённую платформу | Платформа остаётся; destructive delete запрещён |

Структурные наблюдения и ожидаемые переходы сохранены в [`identity-cases.json`](fixtures/metacritic/identity-cases.json). Fixture подтверждает `ID-01–ID-04`, а `ID-05–ID-11` являются детерминированными contract cases для будущих тестов. Все дают единственный объяснимый результат без сравнения title.

## Ограничения и последующие проверки

- Долговременная неизменность встроенных ID не доказана официальной документацией; parser contract должен сигнализировать их исчезновение и хранить locator history.
- Новый ID на уже занятом locator нельзя автоматически признать миграцией: это может быть reuse или ошибка источника. Нужен конфликт, provenance и отдельное решение.
- Если Metacritic введёт несколько редакционных объектов для одной коммерческой игры, система сохраняет границу источника. Семантическое объединение editions не входит в Must.
- Platform removal и merge не подтверждены source contract; реализация не удаляет существующие варианты по одному отсутствующему snapshot.
- Уникальные constraints, alias migration и конфликтные ветки должны быть проверены integration/concurrency tests после выбора БД.

## Проверка критерия выхода

- [x] Определён внешний `game_key`, доступный уже в list items.
- [x] Определена граница Game/GamePlatform и два уровня platform identity.
- [x] Правило применено к list/detail, detail/review, multiplatform и similar-title cases.
- [x] Зафиксированы changed-title, changed-slug, alias-collision, missing-ID и partial-platform outcomes.
- [x] Указаны минимальные unique constraints и запрет эвристического merge.
- [x] Ограничение недокументированных SSR IDs превращено в failure contract и остаточный риск.

**Вывод:** правило достаточно для test-first реализации уникальных ограничений, daily dedupe и idempotent upsert. `R-ID-01` переходит из исследования в митигацию; финальное доказательство остаётся за integration/concurrency tests.
