import hashlib
import json

import pytest

from src.mcp_server.security.client_registry import ClientRegistry


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@pytest.fixture
def registry_file(tmp_path):
    path = tmp_path / "mcp_clients.json"
    path.write_text(
        json.dumps(
            {
                "clients": [
                    {
                        "client_id": "worker-a",
                        "token_hash": _hash("token-a"),
                        "allowed_tools": ["execute_refund"],
                    },
                    {
                        "client_id": "worker-b",
                        "token_hash": _hash("token-b"),
                        "allowed_tools": ["validate_fraud_score"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_authenticate_derives_client_id_from_matching_token(registry_file):
    registry = ClientRegistry.from_file(registry_file)

    client = registry.authenticate("token-a")

    assert client is not None
    assert client.client_id == "worker-a"


def test_authenticate_rejects_unknown_token(registry_file):
    registry = ClientRegistry.from_file(registry_file)

    assert registry.authenticate("not-a-real-token") is None


def test_authenticate_rejects_empty_token(registry_file):
    registry = ClientRegistry.from_file(registry_file)

    assert registry.authenticate("") is None


def test_is_allowed_checks_per_client_allowlist(registry_file):
    registry = ClientRegistry.from_file(registry_file)
    worker_a = registry.authenticate("token-a")
    worker_b = registry.authenticate("token-b")

    assert registry.is_allowed(worker_a, "execute_refund") is True
    assert registry.is_allowed(worker_a, "validate_fraud_score") is False
    assert registry.is_allowed(worker_b, "validate_fraud_score") is True


def test_worker_default_may_call_the_read_tools():
    """The shipped registry (mcp_clients.json) must allowlist the read tools
    for the worker, or every evidence fetch is denied at the boundary."""
    registry = ClientRegistry.from_file("mcp_clients.json")
    worker = next(c for c in registry._clients if c.client_id == "worker-default")

    assert registry.is_allowed(worker, "get_order")
    assert registry.is_allowed(worker, "get_refund_history")
