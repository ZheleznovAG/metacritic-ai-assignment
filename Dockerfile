ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.11@sha256:79c6f4776b851471cc73b7d21d0cc834bb94383c292e83640d27eff512864df7
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC
ENV TIKTOKEN_CACHE_DIR=/opt/app/tokenizer-cache
WORKDIR /opt/app

FROM base AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
# tiktoken verifies the downloaded vocabulary against its pinned SHA-256. Package it once
# at build time so checks and the non-root runtime can tokenize without network or writes.
RUN .venv/bin/python -c "import tiktoken; tiktoken.get_encoding('o200k_harmony')" \
    && chmod -R a=rX /opt/app/tokenizer-cache

FROM dependencies AS checks
RUN uv sync --locked --no-install-project
ENV PATH="/opt/app/.venv/bin:$PATH"
# Browser binaries and OS libraries are fetched only while building the checks image.
RUN python -m playwright install --with-deps --only-shell chromium
COPY app ./app
COPY scripts ./scripts
COPY research/planning ./research/planning
COPY research/feasibility ./research/feasibility
COPY evals/reviews ./evals/reviews
COPY evals/review_selection ./evals/review_selection
COPY evals/similarity ./evals/similarity
COPY docs ./docs
COPY action_plan.md implementation_plan.md ./
COPY intake.md assignment.md methodology.md AGENTS.md README.md ./
CMD ["python", "scripts/check.py"]

FROM base AS runtime
COPY --from=dependencies /opt/app/.venv /opt/app/.venv
COPY --from=dependencies /opt/app/tokenizer-cache /opt/app/tokenizer-cache
ENV PATH="/opt/app/.venv/bin:$PATH"
COPY app ./app
COPY scripts/provision_db.py ./scripts/provision_db.py
COPY scripts/grant_manual_run_access.py ./scripts/grant_manual_run_access.py
# Public build-only placeholders, never production credentials; no DB connection.
RUN APP_ENV=build DJANGO_SECRET_KEY=build-only-placeholder-not-for-runtime-000000000000000000000000 \
    DJANGO_ALLOWED_HOSTS=localhost POSTGRES_DB=build DATABASE_USER=build \
    DATABASE_PASSWORD=build POSTGRES_HOST=localhost \
    python app/manage.py collectstatic --noinput
ARG APP_VERSION=local
RUN python -c "import os,re; from pathlib import Path; v=os.environ['APP_VERSION']; assert re.fullmatch(r'[a-zA-Z0-9._-]{1,80}',v); Path('app/build-version.txt').write_text(v+'\n',encoding='utf-8')"
LABEL org.opencontainers.image.version=${APP_VERSION}
USER 65532:65532
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=8s --start-period=15s --retries=3 \
    CMD ["python", "app/healthcheck.py"]
CMD ["gunicorn", "--chdir", "app", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", "--worker-tmp-dir", "/tmp", "config.wsgi:application"]
