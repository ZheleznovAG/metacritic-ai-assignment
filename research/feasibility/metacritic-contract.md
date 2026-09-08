# `SPK-02` — контракт обязательных данных Metacritic

## Вопрос, граница и решение

**Вопрос:** можно ли из разрешённых страниц Metacritic воспроизводимо получить поля `DATA-02–DATA-03`, раздельные critic/user review inputs и кандидатов `SEL-01–SEL-02`, включая естественно неполные карточки?

**Проверено:** 2026-09-05, 21:56–22:07 `Asia/Novosibirsk` (14:56–15:07 UTC).

**Среда:** локальная рабочая машина; последовательные HTTPS GET без аутентификации, cookies, browser session и обхода защит; тот же идентифицируемый user-agent, что в `SPK-01`, с версией `0.2`.

**Решение:** `Proceed with limitation`.

Все обязательные поля имеют наблюдаемый источник либо проверяемое состояние естественного отсутствия. Однако контракт составной: JSON-LD недостаточно, Userscore и полный набор отзывов платформы требуют platform-specific страниц, выдача списков изменчива, а источник может содержать внутренне несогласованные или семантически подозрительные данные. Поэтому реализация должна хранить provenance, различать `null` и parser failure, фильтровать дневные дубли по стабильной идентичности и не затирать хорошие данные частичным ответом.

Связи: `SEL-01–SEL-02`, `DATA-02–DATA-03`, `AI-01–AI-03`, `ASM-06–ASM-08`, `ASM-11–ASM-13`, `R-EXT-03–R-EXT-04`, `R-SIM-01`, `R-TST-01`.

## Минимальный эксперимент

Проверены домашний раздел [Games](https://www.metacritic.com/game/), две страницы [SEE ALL / All New Games](https://www.metacritic.com/browse/game/all/all/all-time/new/), обычная одноплатформенная карточка [Twisted Tower](https://www.metacritic.com/game/twisted-tower/), зрелая мультиплатформенная карточка [Elden Ring](https://www.metacritic.com/game/elden-ring/) и естественно неполная свежая карточка [Water Margin Heroes: Eight Acts of Battle](https://www.metacritic.com/game/water-margin-heroes-eight-acts-of-battle/). Для матрицы Userscore дополнительно проверены четыре platform-specific user-review URL Elden Ring; PlayStation 5 уже представлен основной карточкой.

Все перечисленные GET вернули `200` и исходный SSR HTML. Полные тела использовались во временном каталоге для ручной сверки, подсчётов и SHA-256, но не публикуются: в Git сохранён минимальный проверяемый контракт без page chrome, рекламы, runtime-конфигурации и избыточного стороннего текста.

Длинные source descriptions представлены коротким excerpt и SHA-256 полного JSON-LD значения; review samples ограничены короткими дословными excerpts. Это сохраняет проверяемость контракта без публикации полного стороннего корпуса.

| Локальный снимок | UTC | Байт распакованного HTML | SHA-256 |
|---|---|---:|---|
| `/game/` | 14:56:02 | 969250 | `7835514FA5AC7EF0898E3C122C3E96774E2FEB3A19DE04DA6ACEEA6812C4421F` |
| SEE ALL, page 1 | 14:56:09 | 343929 | `DB9383F919B889220CD05881A72FBC622E74F1A6F0E3AE59AFBD7C9D0AFC8ACC` |
| Twisted Tower | 14:56:16 | 683198 | `0BCE6358E76CAF9A1F2AF2DB2F5B04B7D87A3882A3D6578A66643E2F1276D486` |
| Elden Ring | 14:56:33 | 761923 | `F67F75FCFFEDEAAC076B4FAD45F8A1FF35B994D19B118B6D687E7079CB35ED0F` |
| Water Margin Heroes | 14:59:00 | 597154 | `6D3D65DE102F3D47B4C94E2DD2650569B9C874FB5A616AA717F36FB5949E7E00` |
| Elden Ring user reviews, Xbox One | 15:03:40 | 460778 | `8D21F42E4BAA2F4AD69CF2D2D84A4D0C0B8AF920AD836D9CB89903A45B6007DB` |
| Elden Ring user reviews, PC | 15:03:43 | 467897 | `5DC17103F2C0E96E69403788319390F42C509232CE270E81C9605697FBAC21EE` |
| Elden Ring user reviews, PlayStation 4 | 15:03:45 | 472330 | `0FA0F37F3FABF21B23A68D672353CD68F7B9FE0A8AB3F447541FE6EFF9BE09E9` |
| Elden Ring user reviews, Xbox Series X | 15:03:48 | 464223 | `9B397549A1536B4D889DE2728D5206B7D9FAD0CD25C7A7B6C0E594A06DF8FE13` |
| SEE ALL, page 2 | 15:07:07 | 338764 | `568217A3C40F8796133D9C24C2E964D76D8105CF255818CC8B94B8C68E91A5E2` |

Дополнительно проверена The Sinking City 2 как второй мультиплатформенный вариант: исходный HTML `200`, 732472 байта, SHA-256 `69AF8F6F0C923620657B586C053B659F24A696A7313397F018AA91ACBF28F490`. Отдельная fixture не сохранена, потому что она не добавляет новый тип контракта к трём выбранным cases.

## Контракт списков

### New Releases

SSR-секция с `aria-label="New Releases content"` содержит ровно 20 `product-card` в исходном порядке. У каждой карточки есть canonical-looking path `/game/<slug>/`, отображаемое название и Metascore. Это достаточный источник для первой партии `SEL-01`; selector должен быть ограничен именно секцией New Releases, потому что `/game/` содержит и другие игровые карусели.

### SEE ALL

Обе проверенные страницы вернули по 24 карточки. Page 1 шла по невозрастающей дате релиза; `?page=2` вернул другой набор, а UI показал активную страницу и дальнейшую пагинацию. Между снимками page 1 и page 2, сделанными с разницей около 11 минут, обнаружено 6 одинаковых URL из 42 уникальных в объединении.

Следствия для `SEL-02`:

- размер source page не равен batch size 20;
- `?page=N` является рабочим navigation contract;
- page number не является стабильной идентичностью позиции;
- selector обязан дедуплицировать по нормализованной идентичности игры и сверяться с дневным processed set;
- mutable выдача не позволяет доказывать исчерпание только сравнением номера страницы или offset.

Датированный порядок и наблюдаемый overlap сохранены в [`fixtures/metacritic/lists.json`](fixtures/metacritic/lists.json).

## Дополнительная проверка review pagination для `PLN-02`

**Проверено:** 2026-09-08 UTC, тем же способом без аутентификации и обхода защит; user-agent контракта обновлён до `0.3`.

SSR review page содержит только начальный segment. Для GTA V / PlayStation 5 user route страница сообщила `393` отзывов и отдала `50` cards. Запросы web route с `?page=0,1,2,3,7` вернули одну и ту же ordered sequence из 50 cards с одинаковым SHA-256. Следовательно, `?page=N` для отзывов использовать нельзя.

В сериализованном SSR state найдена фактическая ссылка `backend.metacritic.com/reviews/.../web` с `offset`, `limit`, `filterBySentiment`, `sort` и объектом `links`. Контролируемый последовательный обход выполнялся только по возвращённому `links.next.href`:

| Audience / route | Source order | Limit | Pages / final page | Reported | Fetched / unique / duplicates | Exhaustion |
|---|---|---:|---|---:|---:|---|
| user, GTA V / PlayStation 5 | `sort=date` | 50 | 8 / 43 | 393 | `393 / 393 / 0` | у offset `350` отсутствует `next` |
| critic, Bayonetta / Xbox 360 | `sort=score` | 10 | 9 / 6 | 86 | `86 / 86 / 0` | у offset `80` отсутствует `next` |

У user records был стабильный source review ID. У critic records поле ID оказалось пустым, поэтому проверка уникальности использовала fallback SHA-256 от publication slug, review URL, score и полного нормализованного quote. Это не объявляет изменившийся critic text той же логической записью, но даёт воспроизводимую identity для конкретного content version.

Отдельный volume probe GTA V / PlayStation 4 сообщил `1,557` user reviews при тех же 50 SSR cards — минимум 32 backend pages. Полный обход этого route намеренно не выполнялся: меньшие complete examples доказывают cursor/exhaustion contract, а большой reported count доказывает, что реализация не может держать весь route в памяти, ограничиваться первой страницей или считать 393 максимумом. Документированный глобальный максимум не найден, поэтому контракт не вводит искусственный total cap: память `O(page limit)`, запросы `O(reported / limit)`, persistent storage `O(unique reviews)`. Реальная ёмкость 80 GB VDS измеряется отдельно в `HRD-05/PUB-02`; до такого evidence бессрочная retention capacity не заявляется и reviews молча не отбрасываются.

Полное обезличенное evidence без текстов отзывов находится в [`reviews-pagination.json`](fixtures/metacritic/reviews-pagination.json). Из него следует контракт реализации:

1. Backend link принимается только после allowlist-проверки HTTPS origin, path identity, game/platform/audience, `filterBySentiment`, `sort`, `limit` и component fields. Произвольный URL из внешнего ответа не запрашивается.
2. Каждая страница, все её reviews и следующий cursor сохраняются одной транзакцией. Повтор после сбоя идемпотентен; worker обрабатывает одну страницу за claim, поэтому количество страниц не ограничено RAM или lease одного вызова.
3. Source order задаётся подтверждённым `sort` и ordinal внутри последовательности pages; его нельзя заменять порядком БД. Любые изменение route parameters, cursor loop, повтор ordered page identities или изменение `totalResults` переводят generation в `unstable`, а не в `complete`.
4. Exhaustion наступает только при отсутствии `next`. `complete` требует успеха всех pages, стабильного reported total, отсутствия нерешённых дублей и равенства unique fetched count `totalResults`; отдельно различаются `empty`, `retryable`, `unstable` и `failed`.
5. Каждый полученный review сохраняется в исходном языке независимо от попадания в AI corpus. Summary создаётся после полного terminal snapshot всех известных platform routes аудитории, а не после каждой страницы; при незавершённой новой generation остаётся видим предыдущий summary со stale state.

Это датированное наблюдение внешнего недокументированного контракта, а не гарантия Metacritic. Sanitised fixture и controlled live contract check остаются обязательными перед выпуском и при изменении parser contract.

## Карта происхождения полей

| Поле | Первичный источник | Резервная/проверочная структура | Контракт отсутствия |
|---|---|---|---|
| Название | JSON-LD `VideoGame.name` | `h1` в product hero | Пустое значение — invalid core response |
| Canonical source | JSON-LD `VideoGame.url` и request URL | `/game/<slug>/` из списка | Отсутствие — invalid core response |
| Обложка | JSON-LD `VideoGame.image` | hero media/image | `null` допустим только на валидной карточке и не затирает ранее хорошее значение |
| Разработчик | DOM hero metadata после `Developer:` | details/credits link | JSON-LD в проверенных карточках developer не содержал; отсутствие DOM-поля — `null` только после валидации карточки |
| Описание | JSON-LD `VideoGame.description` | product summary | Естественная пустота — `null`; подозрительное содержимое хранится с provenance, а не «исправляется» парсером |
| Видео | JSON-LD `VideoGame.trailer.embedUrl` и `contentUrl` | product media | Нет `trailer` — `null`, не parser error |
| Платформы | JSON-LD `VideoGame.gamePlatform` | Details и All Platforms cards | Ноль платформ — invalid core response |
| Metascore платформы | All Platforms card с platform slug и `title="Metascore …"` | platform critic-review page | `tbd` → `null`, не `0` |
| Userscore платформы | `/user-reviews/?platform=<slug>` | выбранная hero platform только для default variant | `TBD`/недостаточно ratings → `null`, не `0` |
| Отзывы критиков | `/critic-reviews/?platform=<slug>` review cards | ограниченные snippets основной карточки | Пустая валидная страница → пустая коллекция |
| Отзывы пользователей | `/user-reviews/?platform=<slug>` review cards | ограниченные snippets основной карточки | Пустая валидная страница → пустая коллекция |

Query `?platform=pc` на основной карточке Elden Ring при ручной проверке не переключил hero/review content с default PlayStation 5. Поэтому платформенные оценки и отзывы нельзя извлекать, просто добавляя query к `/game/<slug>/`; нужны явные critic/user review routes, которые сами показывают выбранную платформу.

## Репрезентативные cases

| Case | Наблюдение | Fixture |
|---|---|---|
| Обычная одноплатформенная | Twisted Tower: PC, Metascore 75, Userscore 5.2, developer/description/cover и оба типа отзывов доступны; trailer естественно отсутствует | [`ordinary-game.json`](fixtures/metacritic/ordinary-game.json) |
| Мультиплатформенная | Elden Ring: 5 платформ; пары различаются, включая `Metascore=null` при существующем Userscore; critic/user inputs разделены | [`multiplatform-game.json`](fixtures/metacritic/multiplatform-game.json) |
| Неполная | Water Margin Heroes: title/cover/developer/description/platform доступны, оба score — `null`, отзывов и trailer нет | [`incomplete-game.json`](fixtures/metacritic/incomplete-game.json) |

Elden Ring одновременно показал внутреннюю изменчивость счётчиков: JSON-LD/All Platforms и hero critic-review count различались, хотя сам Metascore совпал. Счётчики не входят в Must и не должны использоваться как идентичность или доказательство полноты выборки отзывов.

У Water Margin Heroes название не соответствует описанию про basketball shooter. Это наблюдаемая семантическая аномалия источника, а не доказанная ошибка извлечения. Реализация должна сохранить исходное значение и provenance, пометить такую запись диагностически при доступной проверке, но не выдумывать исправленное описание.

## Ограничения реализации

Стабильная identity, на которую ссылается этот контракт, уточнена последующим `SPK-03`: правила `game-title.id`, платформенных ID, aliases и конфликтов находятся в [`game-identity.md`](game-identity.md) и [`identity-cases.json`](fixtures/metacritic/identity-cases.json).

- Парсеру нужны одновременно JSON-LD и устойчивые semantic/test attributes DOM; одного источника недостаточно.
- Полная матрица и review corpus требуют bounded fan-out по платформам. Нужны cache, timeout/backoff, лимит запросов и отсутствие повторного GET при неизменном source fingerprint.
- `null` разрешён только после успешной классификации валидной карточки; исчезновение ранее присутствовавшего selector или массовый рост `null` — структурная ошибка.
- Все внешние тексты недоверенные: user reviews уже содержат нерелевантные утверждения, multilingual content и потенциально инструктивный текст. До `SPK-05` они считаются data, а не инструкциями.
- Curated JSON fixtures фиксируют наблюдаемую структуру, короткие excerpts, hashes и expected values; они не являются исходным входом executable parser tests. Минимальные sanitised HTML/SSR fragments и expected extraction добавляются до реализации соответствующего parser в `IMP-02`; review backend page/cursor inputs — в `IMP-04`. `HRD-01` расширяет уже существующий набор повреждёнными и отказными вариантами. Обычный CI не выполняет live scrape.
- `SPK-03` определил ID-first identity и upsert-границу; URL/slug из этого spike используется только как наблюдаемый locator, не как первичный ключ.

## Диспозиция

`SPK-02` проходит критерий выхода с решением `Proceed with limitation`: для каждого обязательного поля известен источник либо явное ограничение, не отменяющее Must. URL/platform cases использованы в `SPK-03`, а раздельные review samples готовы для `SPK-05`. Остаточный риск будущих вариантов разметки остаётся у `R-EXT-04` и должен закрываться schema validation, fixture/failure tests и отдельным controlled live contract check.
