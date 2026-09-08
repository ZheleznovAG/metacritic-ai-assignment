# `SPK-05` review-summary eval

Этот каталог хранит замороженный до baseline-run набор оценки AI-резюме для `AI-01–AI-03`.

## Состав

- [`cases.json`](cases.json) — project-authored synthetic inputs и case-specific oracles;
- [`prompt.md`](prompt.md) — system instruction `3.0.0` и точный user payload contract;
- [`output.schema.json`](output.schema.json) — structured-output contract;
- [`rubric.md`](rubric.md) — шкала, блокирующие ошибки и неизменяемый порог;
- `run_groq_eval.py` — dependency-free Groq Chat Completions API runner;
- `score_run.py` — deterministic structural checks и шаблон ручной rubric-оценки.
- `check_token_budget.py` — token-aware preflight для production-maximum multilingual input;
- [`token-budget-report.json`](token-budget-report.json) — sanitised local/live evidence без model output.

Синтетические отзывы используются намеренно: короткие source excerpts `SPK-02` подтверждают раздельность routes, но их недостаточно для ordinary/long/contradictory/injection cases и нельзя расширять выдуманными цитатами реальных авторов.

## Безопасная конфигурация

Скопируйте отсутствующие переменные из корневого [`.env.example`](../../.env.example) в локальный `.env`:

```dotenv
GROQ_API_KEY=
GROQ_API_BASE_URL=https://api.groq.com/openai/v1
GROQ_API_MODEL=openai/gpt-oss-20b
GROQ_API_TIMEOUT_SECONDS=180
SPK05_MAX_RETRIES=3
```

`GROQ_API_KEY` и `.env` не коммитятся. Ключ должен принадлежать организации на **Groq Free Plan**; не подключайте Developer Plan к проекту spike. Runner зафиксирован на модели `openai/gpt-oss-20b`, входящей в опубликованные Free Plan limits, и не настраивает платный fallback. В Groq Data Controls рекомендуется включить Zero Data Retention; eval-тексты в любом случае синтетические.

## Последовательность

```powershell
.\.venv\Scripts\python.exe -m pip install -r evals/reviews/requirements-token-budget.txt
.\.venv\Scripts\python.exe evals/reviews/check_token_budget.py
.\.venv\Scripts\python.exe evals/reviews/run_groq_eval.py --check-access
.\.venv\Scripts\python.exe evals/reviews/run_groq_eval.py --dry-run
.\.venv\Scripts\python.exe evals/reviews/run_groq_eval.py --run
.\.venv\Scripts\python.exe evals/reviews/score_run.py .eval-runs/reviews/<run-id>/run.json
# Заполнить ручные оценки в scorecard.json, затем:
.\.venv\Scripts\python.exe evals/reviews/score_run.py .eval-runs/reviews/<run-id>/run.json --finalize
```

`SPK-05` проверен локально на Windows с Python 3.14.7 в ignored `.venv`; VDS для этого spike не используется. `--check-access` вызывает только model listing, но не inference. `--dry-run` проверяет inputs/schema и размеры запросов. Только `--run` отправляет девять отдельных inference requests.

Для production input authoritative limit измеряется токенами, а не символами. `check_token_budget.py` использует официальный для `gpt-oss-20b` tokenizer `o200k_harmony`, обрезает каждый input только по token boundary и считает весь canonical `messages + response_format`. Обычный запуск делает только локальную проверку; `--live` после успешного preflight делает один вызов, сверяет provider usage с guarded estimate и не выводит/не сохраняет model text. Candidate policy: до 10 отзывов × 450 токенов, prompt estimate не более 6,000, completion cap 800 и общий reservation не более 6,800 токенов, оставляя запас относительно 8,000 TPM Free Plan. Character/UTF-8 sizes старого eval-run остаются только диагностикой.

Каждый case выполняется отдельным stateless request. Парные critic/user cases никогда не попадают в один prompt. Tools не включаются; reasoning effort — `low`, reasoning text исключён; заданы `temperature=0`, `seed=7`; output ограничен strict JSON Schema и `max_completion_tokens=800`. Детерминизм API остаётся best effort, поэтому manifest хранит все fingerprints и фактически возвращённую модель.

Runner сохраняет только sanitised fields в игнорируемый `.eval-runs/`: model, параметры, fingerprints, latency, token usage, безопасные rate-limit headers и model JSON. Provider request IDs, остальные headers и API key не сохраняются. Ошибка одного case изолируется, transient `429/5xx` повторяется с ограниченным backoff, а системные `400/401/403/404` останавливают run. Groq не поддерживает `uniqueItems`; provider-side `minItems`/`maxItems` также скрывают некачественный output за `json_validate_failed`. Поэтому API-адаптер снимает эти ограничения только в отправляемой schema. Детерминированный normalizer `1.0.0` обрезает только хвост массивов длиннее 5 и записывает это в `normalizations`; затем каноническая schema и локальный validator проверяют ровно один support ID на тезис и остальные инварианты. После ручной оценки итоговый обезличенный report добавляется в Git отдельным `apply_patch`.

## Free tier и воспроизводимость

Выбран `openai/gpt-oss-20b`: Groq заявляет multilingual benchmark `75.7%`, context `131,072` и strict JSON Schema. Опубликованные на 2026-09-07 лимиты Free Plan для неё: `30 RPM`, `1,000 RPD`, `8,000 TPM`, `200,000 TPD`. Девять последовательных запросов помещаются в request/day и token/day, а `429` по краткосрочному TPM обрабатывается без перехода на платный tier.

Модель, доступность Free Plan и rate limits могут измениться. Их нужно повторно проверить непосредственно перед run. Manifest хранит фактически возвращённое имя модели, timestamp, prompt/cases/schema SHA-256, параметры, usage и latency каждого case.
