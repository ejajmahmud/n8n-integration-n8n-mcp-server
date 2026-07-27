"""HTTP transport for n8n MCP Server.

Runs the MCP server over HTTP/SSE for use as a standalone service.
"""

from __future__ import annotations

import os
from src.server import mcp

def main() -> None:
    """Run the MCP server with HTTP transport."""
    port = int(os.environ.get("MCP_PORT", "3000"))
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    import uvicorn
    app = mcp.http_app()
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()
