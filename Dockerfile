# Pokewalker Client Docker Image
# Uses UV for fast package management

FROM python:3.12-slim

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml README.md ./
COPY pokewalker_client/ ./pokewalker_client/
COPY tests/ ./tests/

# Create virtual environment and install dependencies
RUN uv venv /app/.venv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install the package with all dependencies
RUN uv pip install -e ".[all]"

# Default command - show help
ENTRYPOINT ["pokewalker"]
CMD ["--help"]
