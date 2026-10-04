"""User model for OAuth 2.1 authentication and data isolation."""

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.notification import NotificationPreference
    from app.models.tracker import Tracker


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    # Subject identifier from OAuth 2.1 provider (WorkOS/Stytch)
    oauth_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)

    # Relationships
    trackers: Mapped[list["Tracker"]] = relationship(
        "Tracker", back_populates="user", cascade="all, delete-orphan"
    )
    notification_preference: Mapped["NotificationPreference | None"] = relationship(
        "NotificationPreference", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
