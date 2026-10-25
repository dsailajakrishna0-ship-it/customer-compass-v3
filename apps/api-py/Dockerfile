# Image: slim Python 3.12 base; uv installs deps, uvicorn serves the FastAPI app on port 8001
FROM python:3.12-slim

# Install uv (fast Python package manager) — see
# https://docs.astral.sh/uv/guides/integration/docker/
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached layer, unchanged unless deps change)
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# Then copy the actual app code
COPY app ./app

RUN uv sync --locked --no-dev

EXPOSE 8001
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
