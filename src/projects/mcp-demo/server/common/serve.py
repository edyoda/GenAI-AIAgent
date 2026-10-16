"""Run one MCPServer as its own process over Streamable HTTP."""

from __future__ import annotations

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.config import HOST, ResourceServer


def serve(mcp: MCPServer, server: ResourceServer) -> None:
    @mcp.custom_route("/health", methods=["GET"])  # unauthenticated liveness probe
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": server.name})

    app = mcp.streamable_http_app(streamable_http_path="/mcp", host=HOST)
    print(f"{server.name} MCP server → {server.url}  (requires scope {server.required_scope})")
    uvicorn.run(app, host=HOST, port=server.port, log_level="warning")
