"""MCP Server initialization and tool registration for DealWatch.

Uses official Python MCP SDK with Streamable HTTP transport at /mcp.
"""

from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from app.mcp import tools

# Initialize MCPServer instance
mcp_server = MCPServer(
    name="DealWatch",
    version="0.1.0",
    instructions=(
        "DealWatch is an AI-powered deal comparison and 14-day price tracking engine. "
        "Use identify_subject to identify a product from a link or query. "
        "Use find_offers to find verified competitor prices. "
        "Use submit_offer_url to verify and add competitor links found via web search. "
        "Use track_subject to start 14-day tracking with price drop and target price alerts."
    ),
)

# Register tools on MCPServer
mcp_server.tool(
    name="identify_subject",
    description="Identifies a product or comparison subject from a retailer link or search query.",
)(tools.identify_subject)

mcp_server.tool(
    name="find_offers",
    description="Finds verified lowest competitor prices and deals for an identified subject.",
)(tools.find_offers)

mcp_server.tool(
    name="submit_offer_url",
    description="Validates and adds a competitor offer URL discovered via web search.",
)(tools.submit_offer_url)

mcp_server.tool(
    name="track_subject",
    description="Starts a 14-day price tracking job for selected offers (max 5 active trackers).",
)(tools.track_subject)

mcp_server.tool(
    name="update_tracker",
    description="Updates target price or alert settings on an existing active tracker.",
)(tools.update_tracker)

mcp_server.tool(
    name="stop_tracking",
    description="Stops an active 14-day price tracker immediately and frees up user tracker quota.",
)(tools.stop_tracking)

mcp_server.tool(
    name="get_tracking_status",
    description="Retrieves tracker countdown, expiration, and monitored offer prices.",
)(tools.get_tracking_status)

mcp_server.tool(
    name="list_trackers",
    description="Lists all price tracking jobs created by the user.",
)(tools.list_trackers)

mcp_server.tool(
    name="get_price_history",
    description="Retrieves chronological point-in-time price observations for an offer.",
)(tools.get_price_history)

mcp_server.tool(
    name="compare_quotes",
    description="Compares point-in-time quotes for travel or on-demand services (Section 10B).",
)(tools.compare_quotes)

# Register UI Resource for ChatGPT Apps SDK
WIDGET_PATH = Path(__file__).parent.parent / "ui" / "dealwatch_widget.html"


@mcp_server.resource(
    "ui://dealwatch/widget.html",
    name="DealWatchWidget",
    description="Interactive ChatGPT App Card Widget for deal discovery and 14-day price tracking",
    mime_type="text/html",
)
async def get_dealwatch_widget() -> str:
    """Returns the self-contained DealWatch interactive card widget HTML."""
    if WIDGET_PATH.exists():
        return WIDGET_PATH.read_text(encoding="utf-8")
    return "<html><body><h3>DealWatch Widget</h3><p>Widget template not found.</p></body></html>"


def create_mcp_app() -> Starlette:
    """Creates the Starlette ASGI sub-app exposing Streamable HTTP transport at /mcp."""
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=transport_security,
    )
