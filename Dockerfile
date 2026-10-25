# Modified by Tofu on 2026-10-25 (https://github.com/tofu-gallery/bracket): the frontend calls the API at /api on its
# own address, the image runs as production with the frontend served by the API, demo accounts are off, and the
# server listens on PORT, as root. See TOFU.md.

# Build static frontend files
FROM node:26-alpine AS builder

WORKDIR /app

ENV NODE_ENV=production

COPY frontend .

RUN apk add pnpm && \
    CI=true pnpm install && \
    VITE_API_BASE_URL=/api pnpm build

# Build backend image that also serves frontend (stored in `/app/frontend-dist`)
FROM python:3.14-alpine3.22
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN rm -rf /var/cache/apk/*

COPY backend /app
WORKDIR /app

# -- Install dependencies:
RUN addgroup --system bracket && \
    adduser --system bracket --ingroup bracket && \
    chown -R bracket:bracket /app
USER bracket

RUN uv sync --no-dev --locked

COPY --from=builder /app/dist /app/frontend-dist

# Tofu: production settings (without ENVIRONMENT, Bracket starts in development, with a fixed admin password and
# JWT secret), the frontend served under the API's own address, no demo accounts, and the address of this copy's
# source code. DATABASE_URL, which Tofu sets, gives PG_DSN and JWT_SECRET at start (backend/bracket/config.py).
ENV ENVIRONMENT=PRODUCTION \
    SERVE_FRONTEND=true \
    API_PREFIX=/api \
    ALLOW_DEMO_USER_REGISTRATION=false \
    SOURCE_URL=https://github.com/tofu-gallery/bracket/tree/pin/2026-10-25.1

EXPOSE 8400

HEALTHCHECK --interval=3s --timeout=5s --retries=10 \
    CMD wget -O /dev/null "http://127.0.0.1:${PORT:-8400}/api/ping"

# Tofu (2026-10-25): the server runs as root. Tofu's container hosting sets PORT=80, and a process that is not root
# cannot bind a port below 1024; the build steps above still run as `bracket`.
USER root

# Tofu: listen on the port Tofu sets (PORT), 8400 without it.
CMD ["/bin/sh", "-c", "exec uv run --no-dev --locked -- gunicorn -k uvicorn.workers.UvicornWorker bracket.app:app --bind 0.0.0.0:${PORT:-8400} --workers 1"]
