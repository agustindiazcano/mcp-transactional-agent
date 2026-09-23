"""Currencies accepted anywhere a refund is expressed.

Shared by the gateway's ingestion schema (src/api/schemas.py) and the MCP
server's argument validation (src/mcp_server/tools/schemas.py), so a claim
the gateway accepts can never carry a currency the refund tool rejects.
Restricting to an enum rather than a free-form string is itself part of the
argument-validation gate (CLAUDE.md Section 5a-i, item 3).
"""

from enum import Enum


class Currency(str, Enum):
    """ISO 4217 codes the refund path supports."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
