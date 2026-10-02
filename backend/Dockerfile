# syntax=docker/dockerfile:1
# Один образ для всех процессов бэкенда (спека §2.1); роль выбирает docker-entrypoint.sh.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Сначала зависимости: слой переиспользуется, пока не менялись pyproject.toml и uv.lock.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
# Клиент Docker нужен только worker и api-admin (управление нодой через прокси, Задача 7.4),
# но образ один. Статический бинарь, без apt-репозитория Docker.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && install -d -o app -g app /var/lib/ocmanager /var/lib/ocmanager-pki
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api-public"]
