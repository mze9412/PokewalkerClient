# Pokewalker Client Docker Image
# Uses UV for fast, reproducible package management

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Stage 1: install dependencies only (layer cached until pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --all-extras

# Stage 2: install project source
COPY pokewalker_client/ ./pokewalker_client/
COPY tests/ ./tests/
RUN uv sync --frozen --all-extras

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["pokewalker"]
CMD ["--help"]
