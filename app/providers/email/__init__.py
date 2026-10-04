"""Email provider package for DealWatch."""

from app.providers.email.brevo import BrevoAPIError, BrevoNotifier, brevo_notifier
from app.providers.email.templates import render_email_alert

__all__ = [
    "BrevoAPIError",
    "BrevoNotifier",
    "brevo_notifier",
    "render_email_alert",
]
