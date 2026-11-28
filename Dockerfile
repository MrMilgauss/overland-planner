# syntax=docker/dockerfile:1
# Overland route planner image (D84/D85/D173/D176). One Dockerfile for linux/amd64 and linux/arm64.
#
# Pinned bases (multi-arch OCI index digests, resolved 2026-11-02 from the registry HTTP API; amd64 + arm64 present):
#   node:22-bookworm-slim          sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da
#   python:3.12-slim-bookworm      sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 (SPIKE-1R)
#   ghcr.io/astral-sh/uv:0.11.16   sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d

# --- Stage 1: the web page, built natively on the build platform (no emulation) ---
FROM --platform=$BUILDPLATFORM node:26-bookworm-slim@sha256:0042e17d232a87a2cd485be1da7900fca4d10a4ad11b29e9285da1d2e54798c9 AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/index.html web/vite.config.ts web/svelte.config.js web/tsconfig.json ./
COPY web/src ./src
RUN npx vite build

# --- Stage 2: Python dependencies and the planner from uv.lock (no dev group), bytecode precompiled ---
FROM python:3.15-slim-bookworm@sha256:498829c717b1e59fc42f0e7865eafe4e04ca0f70a3769d4ae70ba218df54507c AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY REQUIREMENTS.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# --- Stage 3: slim runtime; /app read-only (root-owned), only /data and /road-map-changes writable by uid 10001 ---
FROM python:3.15-slim-bookworm@sha256:498829c717b1e59fc42f0e7865eafe4e04ca0f70a3769d4ae70ba218df54507c AS runtime
ARG GIT_SHA=unknown
ARG COMMIT_TS=1970-01-01T00:00:00Z
ARG ALEMBIC_HEAD=none
LABEL org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/MrMilgauss/overland-planner" \
      org.opencontainers.image.created="${COMMIT_TS}" \
      org.overland.alembic-head="${ALEMBIC_HEAD}" \
      org.overland.commit-ts="${COMMIT_TS}"
RUN groupadd --gid 10001 planner \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin planner \
    && mkdir /data /road-map-changes \
    && chown 10001:10001 /data /road-map-changes
COPY --from=builder /app/.venv /app/.venv
COPY --from=web /build/web/dist /app/web/dist
# Alembic migrations, applied at start (MIGRATIONS_DIR), and alembic.ini for `docker compose run --rm planner alembic`.
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    WEB_DIST_DIR=/app/web/dist \
    MIGRATIONS_DIR=/app/migrations \
    ROUTING_PROVIDER=mock \
    PLANNER_GIT_SHA=${GIT_SHA}
WORKDIR /app
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"]
CMD ["uvicorn", "--factory", "overland_planner.bootstrap.app_factory:create_app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
