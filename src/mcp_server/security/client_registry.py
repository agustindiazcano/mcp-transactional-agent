"""Bearer-token client registry for the MCP security boundary (Phase 1.B).

`client_id` is always derived from *which stored hash matches the presented
token* -- never from a caller-supplied header -- per CLAUDE.md Section 4.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClientRecord:
    client_id: str
    token_hash: str
    allowed_tools: frozenset[str]


class ClientRegistry:
    """In-memory registry of known clients, loaded from a JSON file.

    Expected file shape::

        {"clients": [{"client_id": "...", "token_hash": "<sha256 hex>",
                       "allowed_tools": ["execute_refund"]}]}
    """

    def __init__(self, clients: list[ClientRecord]) -> None:
        self._clients = clients

    @classmethod
    def from_file(cls, path: str) -> ClientRegistry:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_records(raw["clients"])

    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> ClientRegistry:
        """Build a registry from already-parsed client entries, each shaped
        like `{"client_id": ..., "token_hash": ..., "allowed_tools": [...]}`.
        Used directly by `from_file`, and by tests that want a registry with
        a known token without writing a fixture file.
        """
        clients = [
            ClientRecord(
                client_id=str(entry["client_id"]),
                token_hash=str(entry["token_hash"]),
                allowed_tools=frozenset(str(tool) for tool in entry["allowed_tools"]),
            )
            for entry in records
        ]
        return cls(clients)

    def authenticate(self, token: str) -> ClientRecord | None:
        """Hash the presented token and compare it against every registered
        hash in constant time, scanning the whole registry rather than
        returning on the first match. Returns `None` if no stored hash
        matches -- the caller then has no authenticated identity at all.
        """
        presented_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        matched: ClientRecord | None = None
        for client in self._clients:
            if hmac.compare_digest(presented_hash, client.token_hash):
                matched = client
        return matched

    def is_allowed(self, client: ClientRecord, tool: str) -> bool:
        return tool in client.allowed_tools
