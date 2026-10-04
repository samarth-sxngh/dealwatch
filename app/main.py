"""Main FastAPI application for DealWatch."""

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

import app.verticals.products
from app.api.routes.health import router as health_router
from app.config import settings
from app.logging_config import setup_logging

logger = logging.getLogger("dealwatch")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifespan."""
    setup_logging(settings.LOG_LEVEL)
    logger.info(
        "Starting DealWatch API",
        extra={"extra_data": {"environment": settings.ENVIRONMENT, "port": settings.API_PORT}},
    )
    yield
    logger.info("Shutting down DealWatch API")


app = FastAPI(
    title="DealWatch",
    description="Multi-vertical deal comparison and 14-day price tracking platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next) -> Response:
    """Injects request_id and logs request duration."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = request_id

        # Log request summary with request_id attribute for JSONFormatter
        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms}ms)",
            extra={
                "request_id": request_id,
                "duration_ms": duration_ms,
                "status": response.status_code,
            },
        )
        return response
    except Exception:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.exception(
            f"Unhandled exception during {request.method} {request.url.path}",
            extra={"request_id": request_id, "duration_ms": duration_ms},
        )
        raise


# Include route modules
app.include_router(health_router)
