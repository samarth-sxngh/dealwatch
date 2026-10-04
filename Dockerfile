# ==============================================================================
# Stage 1: Build dependency wheels
# ==============================================================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Install compilation headers for C extensions (e.g. psycopg, asyncpg, lxml)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy packaging configuration
COPY pyproject.toml .

# Build wheels for project dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip wheel --no-cache-dir --wheel-dir=/wheels .

# ==============================================================================
# Stage 2: Minimal production runtime
# ==============================================================================
FROM python:3.12-slim-bookworm AS runner

# Optimize Python execution in container
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    ENVIRONMENT=production

WORKDIR /app

# Create non-root application user for defense-in-depth
RUN groupadd -g 10001 dealwatch && \
    useradd -u 10001 -g dealwatch -d /app -s /sbin/nologin dealwatch

# Copy wheels from builder and install into system site-packages
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir /wheels/* && \
    rm -rf /wheels

# Copy application code, database migrations, and scripts
COPY --chown=dealwatch:dealwatch app ./app
COPY --chown=dealwatch:dealwatch alembic ./alembic
COPY --chown=dealwatch:dealwatch alembic.ini .
COPY --chown=dealwatch:dealwatch scripts ./scripts

# Ensure entrypoint script is executable
RUN chmod +x /app/scripts/entrypoint.sh

# Run as non-root user
USER dealwatch

# Expose default HTTP port
EXPOSE 8000

# Container liveness health check using Python standard library
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", 8000)}/health')" || exit 1

# Launch entrypoint
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
