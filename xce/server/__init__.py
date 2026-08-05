"""Server subpackage — MCP protocol server."""

try:
    from xce.server.mcp_server import XCEMCPServer
    __all__ = ["XCEMCPServer"]
except ImportError:
    # MCP package not installed
    __all__ = []

