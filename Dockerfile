# syntax=docker/dockerfile:1.9
FROM python:3.12-slim

# Inherit build arguments for labels
ARG GRAPHITI_VERSION
ARG BUILD_DATE
ARG VCS_REF

# OCI image annotations
LABEL org.opencontainers.image.title="Graphiti FastAPI Server"
LABEL org.opencontainers.image.description="FastAPI server for Graphiti temporal knowledge graphs"
LABEL org.opencontainers.image.version="${GRAPHITI_VERSION}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.vendor="Zep AI"
LABEL org.opencontainers.image.source="https://github.com/getzep/graphiti"
LABEL org.opencontainers.image.documentation="https://github.com/getzep/graphiti/tree/main/server"
LABEL io.graphiti.core.version="${GRAPHITI_VERSION}"

# Install uv using the installer script
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin:$PATH"

# Configure uv for runtime
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Create non-root user
RUN groupadd -r app && useradd -r -d /app -g app app

# Set up the server application first
WORKDIR /app
COPY ./server/pyproject.toml ./server/README.md ./server/uv.lock ./
COPY ./server/graph_service ./graph_service
# Copy the LOCAL graphiti_core (this fork) into the image so the container runs
# OUR graphiti-core (e.g. 0.29.1 with the forward-ported core improvements) — not
# the older version the server lockfile pins from PyPI.
COPY ./pyproject.toml ./README.md /graphiti-core/
COPY ./graphiti_core /graphiti-core/graphiti_core

# Install server deps from the lockfile, then install the LOCAL graphiti-core
# INTO THE PROJECT VENV (/app/.venv) — the upstream Dockerfile installs it with
# `--system`, but the server runs via `uv run`, which uses /app/.venv and never
# /usr/local. Targeting the venv explicitly is what actually makes the fork's
# core (not the lockfile's PyPI pin) the code the server imports.
ARG INSTALL_FALKORDB=false
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev && \
    uv pip install --python /app/.venv/bin/python /graphiti-core

# Change ownership to app user
RUN chown -R app:app /app

# Set environment variables.
# UV_NO_SYNC=1 stops `uv run` (the CMD) from re-syncing /app/.venv to the
# lockfile at container startup — without it, uv would revert our build-time
# local graphiti-core (0.29.1) back to the lockfile's PyPI pin (0.28.2).
ENV PYTHONUNBUFFERED=1 \
    UV_NO_SYNC=1 \
    PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER app

# Set port
ENV PORT=8000
EXPOSE $PORT

# Use uv run for execution
CMD ["uv", "run", "uvicorn", "graph_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
