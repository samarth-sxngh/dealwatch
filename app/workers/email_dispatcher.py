"""Standalone CLI worker for dispatching pending email alert notifications.

Can be run via cron (GitHub Actions or scheduler) or invoked as part of the
daily price check pipeline.
"""

import asyncio
import logging
import sys
from typing import Any

from app.config import settings
from app.database import async_session_factory
from app.logging_config import setup_logging
from app.services.email_dispatcher import EmailDispatcherService

logger = logging.getLogger(__name__)


async def run_email_dispatcher(limit: int = 100) -> dict[str, Any]:
    """Runs one batch pass over pending notifications."""
    async with async_session_factory() as session:
        try:
            service = EmailDispatcherService(session)
            summary = await service.dispatch_pending(limit=limit)
            await session.commit()
            return summary
        except Exception:
            await session.rollback()
            logger.exception("Email Dispatcher Worker failed during run")
            raise


async def main() -> None:
    """CLI entrypoint for standalone execution."""
    setup_logging(settings.LOG_LEVEL)
    logger.info("DealWatch Email Dispatcher Worker launching...")

    try:
        summary = await run_email_dispatcher()
        logger.info("Email Dispatcher Worker completed successfully: %s", summary)
    except Exception:  # noqa: BLE001
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
