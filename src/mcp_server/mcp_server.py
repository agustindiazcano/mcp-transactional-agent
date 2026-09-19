import uvicorn
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("agentic-mcp-engine")

@mcp.tool()
def execute_refund(transaction_id: str, amount: float) -> str:
    """Execute a refund for a transaction."""
    return f"Refund of {amount} for transaction {transaction_id} executed successfully."

@mcp.tool()
def validate_fraud_score(user_id: str) -> float:
    """Validate and get the fraud score for a user."""
    return 0.12

# Create the ASGI app for HTTP/SSE transport
app = mcp.sse_app(message_path="/message")

if __name__ == "__main__":
    uvicorn.run("src.mcp_server.mcp_server:app", host="0.0.0.0", port=8080, reload=True)
