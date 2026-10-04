"""Email notification templates for DealWatch alerts.

Generates responsive, accessible HTML and plain text emails for:
1. price_drop
2. target_reached
3. competitor_cheaper
4. tracking_expired
"""

from typing import Any


def _base_html_layout(
    badge_text: str,
    badge_color: str,
    headline: str,
    content_html: str,
    cta_url: str | None = None,
    cta_text: str = "View Deal Now",
) -> str:
    """Wraps body content in a responsive, inline-styled transactional email template."""
    cta_button_html = ""
    if cta_url:
        cta_button_html = f"""
        <div style="margin: 28px 0; text-align: center;">
            <a href="{cta_url}" style="background-color: #2563eb; color: #ffffff; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px; display: inline-block; box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2);">
                {cta_text} &rarr;
            </a>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{headline}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; line-height: 1.6;">
    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; padding: 32px 16px;">
        <tr>
            <td align="center">
                <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #0f172a; padding: 24px 32px; text-align: left;">
                            <span style="font-size: 20px; font-weight: 800; letter-spacing: -0.5px; color: #ffffff;">
                                &#9889; Deal<span style="color: #38bdf8;">Watch</span>
                            </span>
                        </td>
                    </tr>
                    <!-- Main Card -->
                    <tr>
                        <td style="padding: 32px;">
                            <div style="display: inline-block; padding: 4px 12px; background-color: {badge_color}; color: #ffffff; border-radius: 9999px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 16px;">
                                {badge_text}
                            </div>
                            <h1 style="margin: 0 0 16px 0; font-size: 22px; font-weight: 700; line-height: 1.3; color: #0f172a;">
                                {headline}
                            </h1>
                            {content_html}
                            {cta_button_html}
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f1f5f9; padding: 20px 32px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0;">
                            <p style="margin: 0 0 8px 0;">
                                You are receiving this because you enabled 14-day price tracking on DealWatch.
                            </p>
                            <p style="margin: 0;">
                                &copy; 2026 DealWatch &bull; Free-Tier AI Deal Discovery &amp; Price Intelligence
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


def render_price_drop_email(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Renders price drop alert email (subject, html, text)."""
    title = payload.get("product_title", "Tracked Product")
    retailer = payload.get("retailer", "Retailer")
    prev_price = payload.get("previous_price", "")
    new_price = payload.get("new_price", "")
    currency = payload.get("currency", "")
    drop_amount = payload.get("drop_amount")
    url = payload.get("url")

    subject = f"Price Drop Alert: {title} dropped to {currency} {new_price} at {retailer}!"

    savings_snippet = ""
    if drop_amount:
        savings_snippet = f"""
        <div style="background-color: #ecfdf5; border-left: 4px solid #10b981; padding: 12px 16px; margin: 20px 0; border-radius: 4px;">
            <p style="margin: 0; color: #065f46; font-size: 15px; font-weight: 600;">
                You save {currency} {drop_amount} compared to the previous price!
            </p>
        </div>
        """

    content_html = f"""
    <p style="font-size: 15px; color: #475569; margin: 0 0 20px 0;">
        Great news! The price for <strong>{title}</strong> at <strong>{retailer}</strong> has decreased:
    </p>
    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
        <tr>
            <td style="padding: 8px 12px; font-size: 14px; color: #64748b;">Previous Price:</td>
            <td style="padding: 8px 12px; font-size: 16px; text-decoration: line-through; color: #94a3b8; text-align: right;">{currency} {prev_price}</td>
        </tr>
        <tr>
            <td style="padding: 8px 12px; font-size: 16px; font-weight: 700; color: #0f172a;">New Current Price:</td>
            <td style="padding: 8px 12px; font-size: 22px; font-weight: 800; color: #10b981; text-align: right;">{currency} {new_price}</td>
        </tr>
    </table>
    {savings_snippet}
    """

    html = _base_html_layout(
        badge_text="Price Drop Alert",
        badge_color="#10b981",
        headline=f"Price dropped on {title}",
        content_html=content_html,
        cta_url=url,
        cta_text=f"View Deal on {retailer}",
    )

    text = f"""Price Drop Alert: {title}
Retailer: {retailer}
Previous Price: {currency} {prev_price}
New Price: {currency} {new_price}
{f"Savings: {currency} {drop_amount}" if drop_amount else ""}

Check out the deal: {url or "Open DealWatch to view deal"}
"""
    return subject, html, text


def render_target_reached_email(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Renders target price reached email (subject, html, text)."""
    title = payload.get("product_title", "Tracked Product")
    retailer = payload.get("retailer", "Retailer")
    target_price = payload.get("target_price", "")
    current_price = payload.get("current_price", "")
    currency = payload.get("currency", "")
    url = payload.get("url")

    subject = f"Target Price Reached! {title} is now {currency} {current_price} (Target: {currency} {target_price})"

    content_html = f"""
    <p style="font-size: 15px; color: #475569; margin: 0 0 20px 0;">
        Your price alert has triggered! <strong>{title}</strong> has reached or dropped below your target price at <strong>{retailer}</strong>.
    </p>
    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #eef2ff; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
        <tr>
            <td style="padding: 8px 12px; font-size: 14px; color: #4338ca;">Your Target Price:</td>
            <td style="padding: 8px 12px; font-size: 16px; font-weight: 600; color: #4338ca; text-align: right;">{currency} {target_price}</td>
        </tr>
        <tr>
            <td style="padding: 8px 12px; font-size: 16px; font-weight: 700; color: #312e81;">Current Observed Price:</td>
            <td style="padding: 8px 12px; font-size: 22px; font-weight: 800; color: #4f46e5; text-align: right;">{currency} {current_price}</td>
        </tr>
    </table>
    """

    html = _base_html_layout(
        badge_text="Target Price Reached",
        badge_color="#6366f1",
        headline=f"Your Target Price Was Reached for {title}",
        content_html=content_html,
        cta_url=url,
        cta_text=f"Buy Now on {retailer}",
    )

    text = f"""Target Price Reached! {title}
Retailer: {retailer}
Your Target: {currency} {target_price}
Current Price: {currency} {current_price}

Grab it here: {url or "Open DealWatch to view deal"}
"""
    return subject, html, text


def render_competitor_cheaper_email(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Renders competitor cheaper alert email (subject, html, text)."""
    title = payload.get("product_title", "Tracked Product")
    competitor = payload.get("competitor_retailer", "Competitor")
    original = payload.get("original_retailer", "Original Store")
    savings = payload.get("savings", "")
    currency = payload.get("currency", "")
    message = payload.get("message", "A competitor offers a lower price.")
    url = payload.get("url")

    subject = f"Cheaper Competitor Found: Save {currency} {savings} on {title} at {competitor}!"

    content_html = f"""
    <p style="font-size: 15px; color: #475569; margin: 0 0 16px 0;">
        While monitoring your product across retailers, DealWatch discovered a lower price at <strong>{competitor}</strong> compared to <strong>{original}</strong>:
    </p>
    <div style="background-color: #fffbeb; border: 1px solid #fef3c7; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
        <p style="margin: 0; color: #92400e; font-size: 15px; font-weight: 600;">
            {message}
        </p>
    </div>
    """

    html = _base_html_layout(
        badge_text="Cheaper Competitor Deal",
        badge_color="#f59e0b",
        headline=f"Save on {title} at {competitor}",
        content_html=content_html,
        cta_url=url,
        cta_text=f"View Deal at {competitor}",
    )

    text = f"""Cheaper Deal Found: {title}
{message}
Competitor: {competitor}
Original: {original}
Savings: {currency} {savings}

Link: {url or "Open DealWatch to view deal"}
"""
    return subject, html, text


def render_tracking_expired_email(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Renders tracking expired notification email (subject, html, text)."""
    title = payload.get("product_title", "Tracked Product")
    message = payload.get(
        "message",
        "Your 14-day price tracking period has completed. You can re-start tracking any time.",
    )

    subject = f"14-Day Price Tracking Completed: {title}"

    content_html = f"""
    <p style="font-size: 15px; color: #475569; margin: 0 0 16px 0;">
        Your 14-day tracking cycle for <strong>{title}</strong> has finished.
    </p>
    <p style="font-size: 14px; color: #64748b; margin: 0 0 20px 0;">
        {message}
    </p>
    """

    html = _base_html_layout(
        badge_text="Tracking Completed",
        badge_color="#64748b",
        headline=f"14-Day Tracking Cycle Ended for {title}",
        content_html=content_html,
        cta_url="https://github.com/samarth-sxngh/dealwatch",
        cta_text="Track Another Deal",
    )

    text = f"""14-Day Price Tracking Completed: {title}
{message}
"""
    return subject, html, text


def render_email_alert(alert_type: str, payload: dict[str, Any]) -> tuple[str, str, str]:
    """Dispatches to the appropriate template renderer based on alert type."""
    if alert_type == "price_drop":
        return render_price_drop_email(payload)
    if alert_type == "target_reached":
        return render_target_reached_email(payload)
    if alert_type == "competitor_cheaper":
        return render_competitor_cheaper_email(payload)
    if alert_type == "tracking_expired":
        return render_tracking_expired_email(payload)

    # Generic fallback
    title = payload.get("product_title", "DealWatch Alert")
    subject = f"DealWatch Alert: {title}"
    content = (
        f"<p>{payload.get('message', 'A deal alert was triggered for your tracked item.')}</p>"
    )
    html = _base_html_layout("Deal Alert", "#3b82f6", subject, content)
    text = f"{subject}\n\n{payload.get('message', '')}"
    return subject, html, text
