import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

mcp = MCPServer("agentic-mcp-engine")

# MCPServer.sse_app() defaults allowed_hosts to loopback variants only
# (127.0.0.1:*, localhost:*, [::1]:*), which rejects every request from the
# Worker container in Phase 1.C's docker-compose topology -- there the
# Host header is the Docker Compose service name (e.g. "mcp_server:8080"),
# not localhost, so the MCP SDK's DNS-rebinding protection returns HTTP 421
# "Invalid Host header" on every single request, not just under load.
# Extending (not disabling) the allowlist keeps that protection meaningful.
# "mcp_server" is specific to this docker-compose topology; Phase 6's
# Lambda/serverless topology will need its own allowed_hosts entry.
TRANSPORT_SECURITY = TransportSecuritySettings(
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "mcp_server:*"],
    allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://mcp_server:*"],
)

@mcp.tool()
def execute_refund(transaction_id: str, amount: float) -> str:
    """Execute a refund for a transaction."""
    return f"Refund of {amount} for transaction {transaction_id} executed successfully."

@mcp.tool()
def validate_fraud_score(user_id: str) -> float:
    """Validate and get the fraud score for a user."""
    return 0.12

# Create the ASGI app for HTTP/SSE transport.
# message_path must keep the trailing slash: Starlette's Mount registers
# routes as "<path>/<rest>", so a bare request to "/message" (no sub-path,
# just a query string) 307-redirects to "/message/" -- which httpx's client
# (used internally by mcp.client.sse) does not follow by default, breaking
# every message post. "/messages/" is also the MCP SDK's own default.
app = mcp.sse_app(message_path="/messages/", transport_security=TRANSPORT_SECURITY)

if __name__ == "__main__":
    uvicorn.run("src.mcp_server.mcp_server:app", host="0.0.0.0", port=8080, reload=True)
