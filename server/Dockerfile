FROM python:3.12-slim

WORKDIR /app

# Install curl for Docker healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# Copy application code
COPY . .

# Create data directory for mounted volume
RUN mkdir -p /app/data

EXPOSE 3000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
