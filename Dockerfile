# Hand-rolled override for parbaked's generator — used because the v1.3.0a4
# template references ``ghcr.io/astral-sh/uv:python3.12-slim-bookworm``,
# which doesn't exist on the registry (the correct astral-sh tag for that
# variant is ``python3.12-bookworm-slim``). When that's fixed upstream this
# file can be deleted and parbaked will regenerate the multi-stage build.

# ── Frontend build stage ─────────────────────────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /build
COPY web/ ./
RUN npm ci && npm run build

# ── Runtime stage ────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# uv installs faster than pip; copy the manifest + lockfile first so a
# source edit doesn't bust the dep cache. ``uv.lock*`` is a glob so the
# file is optional.
COPY pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir uv \
    && uv pip install --system --no-cache .

COPY . .

# Bring the built frontend in from the build stage, replacing whatever
# raw source files were copied above. The runtime mounts this directory
# at ``/`` (see parbaked.runtime).
COPY --from=frontend /build/dist ./web/dist

ENV PORT=8000
EXPOSE 8000

CMD ["uvicorn", "parbaked.runtime:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
