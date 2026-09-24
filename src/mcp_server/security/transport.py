"""DNS-rebinding protection settings for the MCP server's SSE transport."""

from mcp.server.transport_security import TransportSecuritySettings

# MCPServer.sse_app() defaults allowed_hosts to loopback variants only
# (127.0.0.1:*, localhost:*, [::1]:*), which rejects every request from the
# Worker container in Phase 1.C's docker-compose topology -- there the
# Host header is the Docker Compose service name (e.g. "mcp_server:8080"),
# not localhost, so the MCP SDK's DNS-rebinding protection returns HTTP 421
# "Invalid Host header" on every single request, not just under load.
# Extending (not disabling) the allowlist keeps that protection meaningful.
DEFAULT_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*", "mcp_server:*"]
DEFAULT_ALLOWED_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://mcp_server:*"]


def parse_hosts(raw: str) -> list[str]:
    """Split a comma-separated host list (the `MCP_ALLOWED_HOSTS` format), dropping blanks."""
    return [host.strip() for host in raw.split(",") if host.strip()]


def build_transport_security(extra_hosts: list[str]) -> TransportSecuritySettings:
    """Build the allowlist: the local defaults plus each deployment host.

    Extra hosts are added exactly, without a port pattern: Cloud Run's Host
    header carries no port, and the SDK's "host:*" pattern only matches a
    host followed by ":<port>". Each one is served over TLS, so its origin
    is https.
    """
    return TransportSecuritySettings(
        allowed_hosts=[*DEFAULT_ALLOWED_HOSTS, *extra_hosts],
        allowed_origins=[*DEFAULT_ALLOWED_ORIGINS, *(f"https://{h}" for h in extra_hosts)],
    )
