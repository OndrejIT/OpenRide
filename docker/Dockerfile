# syntax=docker/dockerfile:1.7
# Build context: repository root (docker compose build, or: docker build -f docker/Dockerfile --target web .)

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.12.13-slim-trixie AS base
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    STATIC_ROOT=/app/staticfiles \
    MEDIA_ROOT=/data/media \
    CACHE_DIR=/data/cache \
    TORCH_HOME=/data/cache/torch
WORKDIR /app
# dependencies are installed per target before the code is copied, so code changes keep the (torch-sized) layers
COPY pyproject.toml uv.lock ./

FROM oven/bun:1.4.3 AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
RUN bun run build

FROM base AS web
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-default-groups --no-install-project
COPY pipeline pipeline
COPY backend backend
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-default-groups
COPY --from=frontend /frontend/dist frontend/dist
WORKDIR /app/backend
# settings require these; collectstatic touches neither the database nor Redis
RUN SECRET_KEY=build DATABASE_URL=sqlite:// REDIS_URL=redis://localhost python manage.py collectstatic --noinput
COPY docker/web-entrypoint.sh /usr/local/bin/web-entrypoint.sh
ENTRYPOINT ["web-entrypoint.sh"]
EXPOSE 8000
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3"]

FROM base AS worker
# git: GeoCalib is installed from its repository
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --group pipeline --group video --no-install-project
COPY pipeline pipeline
COPY backend backend
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --group pipeline --group video
WORKDIR /app/backend
# processing is CPU-bound and one video takes long: one at a time
# videos stuck in queued / processing (restart, emptied Redis) are sent again first
CMD ["sh", "-c", "python manage.py requeue_stuck && exec python manage.py rundramatiq --processes 1 --threads 1"]
