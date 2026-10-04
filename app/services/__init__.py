"""Services exports for DealWatch."""

from app.services.deal_service import DealService
from app.services.notification_service import (
    BaseNotifier,
    LoggingNotifier,
    NotificationService,
)
from app.services.price_service import PriceService
from app.services.product_service import (
    ProductService,
    generate_product_normalized_key,
)
from app.services.tracking_service import (
    QuotaExceededError,
    TrackerNotFoundError,
    TrackingService,
)

__all__ = [
    "BaseNotifier",
    "DealService",
    "LoggingNotifier",
    "NotificationService",
    "PriceService",
    "ProductService",
    "QuotaExceededError",
    "TrackerNotFoundError",
    "TrackingService",
    "generate_product_normalized_key",
]
