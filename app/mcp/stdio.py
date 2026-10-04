"""DealWatch Stdio MCP transport runner for Claude Desktop.

Enables native local Claude Desktop integration over standard input/output.
Note: Standard output is reserved strictly for JSON-RPC messages;
all server logging is directed to stderr.
"""

import asyncio
import logging
import sys

from app.config import settings
from app.mcp.server import mcp_server


def main() -> None:
    """Entrypoint for local stdio MCP server."""
    # Stdio transport does not transmit HTTP Bearer tokens from Claude Desktop;
    # automatically allow local user fallback for stdio sessions.
    settings.AUTH_REQUIRED = False

    # Ensure logs never pollute stdout (which would corrupt JSON-RPC protocol)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("dealwatch").info(
        "Starting DealWatch MCP Server in stdio mode for Claude Desktop"
    )
    asyncio.run(mcp_server.run_stdio_async())


if __name__ == "__main__":
    main()
