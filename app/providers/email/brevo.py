"""Brevo (formerly Sendinblue) Transactional Email Client and Notifier."""

import logging
from typing import Any

import httpx

from app.config import settings
from app.providers.email.templates import render_email_alert
from app.services.notification_service import BaseNotifier

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoAPIError(Exception):
    """Raised when Brevo REST API returns an error."""

    def __init__(self, status_code: int, message: str, error_code: str | None = None) -> None:
        super().__init__(f"Brevo API error ({status_code}) [{error_code}]: {message}")
        self.status_code = status_code
        self.message = message
        self.error_code = error_code


class BrevoNotifier(BaseNotifier):
    """Transactional email sender backed by Brevo v3 REST API.

    Implements BaseNotifier to cleanly slot into NotificationService and
    PriceCheckerWorker pipelines.
    """

    def __init__(
        self,
        api_key: str | None = None,
        sender_email: str | None = None,
        sender_name: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = settings.BREVO_API_KEY if api_key is None else api_key
        self.sender_email = sender_email or settings.BREVO_SENDER_EMAIL or "alerts@dealwatch.local"
        self.sender_name = sender_name or settings.BREVO_SENDER_NAME or "DealWatch"
        self.timeout = timeout

    async def send_transactional_email(
        self,
        recipient_email: str,
        subject: str,
        html_content: str,
        text_content: str,
        recipient_name: str | None = None,
    ) -> dict[str, Any]:
        """Dispatches an email through Brevo's v3 SMTP REST API endpoint.

        Args:
            recipient_email: Destination email address.
            subject: Email subject line.
            html_content: Fully rendered HTML body.
            text_content: Plain text body fallback.
            recipient_name: Optional recipient display name.

        Returns:
            Dict containing Brevo response metadata (e.g. {'messageId': '...'}).

        Raises:
            BrevoAPIError: If Brevo rejects the request.
        """
        # Fallback dry-run if no API key is configured
        if not self.api_key:
            logger.warning(
                "BREVO_API_KEY is not configured. Simulating email delivery to %s for subject '%s'.",
                recipient_email,
                subject,
            )
            return {"simulated": True, "messageId": "dry-run-message-id"}

        payload = {
            "sender": {
                "name": self.sender_name,
                "email": self.sender_email,
            },
            "to": [
                {
                    "email": recipient_email,
                    "name": recipient_name or recipient_email.split("@")[0],
                }
            ],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content,
        }

        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(BREVO_API_URL, json=payload, headers=headers)
            except httpx.RequestError as exc:
                logger.error("HTTP network error communicating with Brevo API: %s", exc)
                raise BrevoAPIError(
                    status_code=500,
                    message=f"Network error communicating with Brevo: {exc}",
                ) from exc

        if response.status_code in (200, 201, 202):
            data = response.json()
            logger.info(
                "Successfully dispatched email via Brevo to %s (messageId: %s)",
                recipient_email,
                data.get("messageId"),
            )
            return data

        error_data = {}
        try:
            error_data = response.json()
        except (ValueError, TypeError):
            pass

        err_msg = error_data.get("message", response.text)
        err_code = error_data.get("code")

        logger.error(
            "Brevo API error %d: %s [code=%s]",
            response.status_code,
            err_msg,
            err_code,
        )
        raise BrevoAPIError(
            status_code=response.status_code,
            message=err_msg,
            error_code=err_code,
        )

    async def send(
        self,
        recipient: str,
        subject: str,
        message: str,
        payload: dict[str, Any],
    ) -> bool:
        """BaseNotifier interface implementation.

        Renders templates based on alert type in payload and dispatches via Brevo.
        """
        alert_type = payload.get("type", "generic")
        rendered_subject, html_content, text_content = render_email_alert(alert_type, payload)

        # Allow explicit subject override if provided
        final_subject = subject or rendered_subject

        try:
            await self.send_transactional_email(
                recipient_email=recipient,
                subject=final_subject,
                html_content=html_content,
                text_content=text_content,
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to send notification email to %s: %s", recipient, e)
            return False


brevo_notifier = BrevoNotifier()
