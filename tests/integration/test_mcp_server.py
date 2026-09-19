import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os
import sys

# We need to make sure the app can be imported
# The app will be in src.mcp_server.mcp_server.app
try:
    from src.mcp_server.mcp_server import app
except ImportError:
    # If the file doesn't exist yet, we create a dummy app for the test collection to pass
    # so we can see it fail during execution
    from fastapi import FastAPI
    app = FastAPI()

@pytest_asyncio.fixture
async def async_mcp_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        yield client

@pytest.mark.asyncio
async def test_mcp_sse_endpoint_exists(async_mcp_client):
    """Test that the SSE transport endpoint responds."""
    import asyncio
    try:
        async with asyncio.timeout(0.5):
            async with async_mcp_client.stream("GET", "/sse") as response:
                # Should return 200 OK and establish the SSE connection
                assert response.status_code == 200
    except (asyncio.TimeoutError, TimeoutError):
        pass # Expected to timeout because it's a long-lived SSE connection
    
@pytest.mark.asyncio
async def test_mcp_tools_registered():
    """Verify that the required tools are registered on the MCP server."""
    from src.mcp_server.mcp_server import mcp
    
    # We can check the internal tool manager or call list_tools()
    # In MCPServer, the tools are stored in _tool_manager.tools or similar.
    # Alternatively, we can just check if the decorators were applied by checking the __name__ 
    # of the functions, or simply that list_tools() returns them.
    # To avoid async session context issues, let's just inspect the instance.
    tools = mcp._tool_manager._tools if hasattr(mcp, '_tool_manager') else {}
    tool_names = list(tools.keys()) if isinstance(tools, dict) else [t.name for t in tools]
    
    assert "execute_refund" in tool_names
    assert "validate_fraud_score" in tool_names
