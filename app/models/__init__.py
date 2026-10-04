"""Model exports for DealWatch."""

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.notification import Notification, NotificationPreference
from app.models.observation import Observation
from app.models.offer import Offer
from app.models.source import Source
from app.models.subject import ProductDetails, Subject
from app.models.tracker import TrackedOffer, Tracker
from app.models.user import User

__all__ = [
    "Base",
    "Notification",
    "NotificationPreference",
    "Observation",
    "Offer",
    "ProductDetails",
    "Source",
    "Subject",
    "TimestampMixin",
    "TrackedOffer",
    "Tracker",
    "UUIDPrimaryKeyMixin",
    "User",
]
