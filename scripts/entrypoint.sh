#!/usr/bin/env sh
set -e

# DealWatch Container Entrypoint
echo "==> Starting DealWatch in environment: ${ENVIRONMENT:-production}"
echo "==> Listening on port: ${PORT:-8000}"

# Run database migrations if DATABASE_URL or DATABASE_URL_UNPOOLED is configured
if [ -n "$DATABASE_URL" ] || [ -n "$DATABASE_URL_UNPOOLED" ]; then
    echo "==> Applying database migrations with Alembic..."
    if alembic upgrade head; then
        echo "==> Database migrations applied successfully."
    else
        echo "==> WARNING: Alembic migrations failed or were interrupted."
    fi
else
    echo "==> No DATABASE_URL provided; skipping Alembic migrations."
fi

# Execute Uvicorn server replacing shell as PID 1
echo "==> Launching Uvicorn ASGI server..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips "*"
