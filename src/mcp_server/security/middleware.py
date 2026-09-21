"""ASGI-level authn/authz/validation/audit boundary for the MCP server
(Phase 1.B). See CLAUDE.md Section 4 and 5a-i.

Wraps the whole `mcp.sse_app()` ASGI app, so every HTTP request -- the `/sse`
handshake and every `/messages/` JSON-RPC POST -- passes through here first:

1. Authenticate: derive `client_id` from the `Authorization: Bearer` header
   by hashing the presented token and comparing against the registry in
   constant time (never trust a caller-supplied identity header). Missing or
   invalid -> 401, before anything else runs.
2. For a `tools/call` JSON-RPC request specifically: check the tool against
   the authenticated client's allowlist (403 if not permitted), then validate
   the raw arguments against that tool's strict schema in
   `src.mcp_server.tools.schemas` (422 on a business-limit violation or an
   unknown field).
3. Write an audit row. On the allow path this happens *before* the call is
   forwarded to the real MCP app, and a failed write denies the call (503)
   instead of letting it through -- the fail-closed rule in CLAUDE.md Section
   4. On a deny path the audit write is best-effort: the call is already
   denied regardless of whether the write succeeds, so a DB outage there
   only costs an audit entry, never a wrongly-allowed call.

Limitation: the SSE transport delivers a `tools/call` response asynchronously
over the separate `/sse` stream, not as this POST's HTTP response body, so
this middleware cannot observe the tool's actual result. The `result` field
on an ALLOWED row therefore records `"invoked"`, not the eventual
success/failure -- capturing that would need either a mutable audit row or a
second correlated one, which would break the insert-only audit trail this
implementation deliberately keeps. Tool-visibility filtering on `tools/list`
has the same response-delivery limitation and is not implemented here: a
denied client still cannot call a tool outside its allowlist, but it can see
the tool's name in a listing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.mcp_server.security.audit import AuditDecision, write_audit_log
from src.mcp_server.security.client_registry import ClientRegistry
from src.mcp_server.tools.schemas import TOOL_ARG_SCHEMAS

logger = logging.getLogger(__name__)


def _extract_bearer_token(header_value: str | None) -> str | None:
    if not header_value:
        return None
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _parse_jsonrpc_message(body: bytes) -> dict[str, Any] | None:
    try:
        message = json.loads(body)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


def _replay_body(body: bytes) -> Receive:
    """Build a `receive` callable that replays an already-consumed body, so
    the wrapped app can read it again via its own `Request` instance."""
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


class MCPSecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        registry: ClientRegistry,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        self._app = app
        self._registry = registry
        self._session_maker = session_maker

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request = Request(scope, receive)
        token = _extract_bearer_token(request.headers.get("authorization"))
        client = self._registry.authenticate(token) if token else None

        if client is None:
            await self._deny(
                scope,
                receive,
                send,
                status_code=401,
                client_id="unknown",
                tool=None,
                arguments={},
                decision="DENIED_UNAUTHENTICATED",
                message="invalid_or_missing_token",
            )
            return

        if scope["method"] != "POST":
            # The /sse handshake and any non-tool-call traffic: authenticated
            # is enough, per-tool authorization only gates tools/call below.
            await self._app(scope, receive, send)
            return

        body = await request.body()
        receive = _replay_body(body)

        message = _parse_jsonrpc_message(body)
        if message is None or message.get("method") != "tools/call":
            await self._app(scope, receive, send)
            return

        params = message.get("params") or {}
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}

        if not self._registry.is_allowed(client, tool_name):
            await self._deny(
                scope,
                receive,
                send,
                status_code=403,
                client_id=client.client_id,
                tool=tool_name,
                arguments=arguments,
                decision="DENIED_UNAUTHORIZED",
                message="tool_not_permitted",
            )
            return

        schema = TOOL_ARG_SCHEMAS.get(tool_name)
        if schema is not None:
            try:
                schema.model_validate(arguments)
            except ValidationError as exc:
                await self._deny(
                    scope,
                    receive,
                    send,
                    status_code=422,
                    client_id=client.client_id,
                    tool=tool_name,
                    arguments=arguments,
                    decision="DENIED_VALIDATION",
                    message=str(exc),
                )
                return

        try:
            async with self._session_maker() as session:
                await write_audit_log(
                    session,
                    client_id=client.client_id,
                    tool=tool_name,
                    arguments=arguments,
                    decision="ALLOWED",
                    result="invoked",
                )
        except Exception:
            logger.exception("mcp_audit_write_failed; denying call (fail-closed)")
            await JSONResponse({"error": "audit_unavailable"}, status_code=503)(scope, receive, send)
            return

        await self._app(scope, receive, send)

    async def _deny(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        client_id: str,
        tool: str | None,
        arguments: dict[str, Any],
        decision: AuditDecision,
        message: str,
    ) -> None:
        try:
            async with self._session_maker() as session:
                await write_audit_log(
                    session,
                    client_id=client_id,
                    tool=tool,
                    arguments=arguments,
                    decision=decision,
                    result="not_executed",
                )
        except Exception:
            logger.exception("mcp_audit_write_failed for denied call; still denying")

        response = JSONResponse({"error": message}, status_code=status_code)
        await response(scope, receive, send)
