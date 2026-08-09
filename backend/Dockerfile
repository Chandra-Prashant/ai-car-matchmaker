FROM python:3.12-slim

# uv, for the same resolver used in development
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, so code changes do not invalidate the layer.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/app ./app

# Seeded at build time so the image ships with a populated catalogue and
# `docker compose up` needs no setup step.
ENV DATABASE_PATH=/data/marketplace.db
RUN mkdir -p /data && uv run python -m app.inventory.generator --out /data/marketplace.db

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
