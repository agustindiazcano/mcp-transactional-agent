from src.mcp_server.security.transport import build_transport_security, parse_hosts

CLOUD_HOST = "mcp-server-123456789.us-central1.run.app"


def test_defaults_keep_loopback_and_compose_hosts():
    security = build_transport_security([])

    assert security.allowed_hosts == ["127.0.0.1:*", "localhost:*", "[::1]:*", "mcp_server:*"]
    assert security.allowed_origins == [
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://mcp_server:*",
    ]


def test_extra_host_is_allowed_exactly_with_its_https_origin():
    # Cloud Run's Host header has no port, and the SDK's "host:*" pattern
    # only matches a host followed by a port, so the entry must be exact.
    security = build_transport_security([CLOUD_HOST])

    assert CLOUD_HOST in security.allowed_hosts
    assert f"https://{CLOUD_HOST}" in security.allowed_origins
    assert "localhost:*" in security.allowed_hosts


def test_dns_rebinding_protection_stays_enabled():
    assert build_transport_security([CLOUD_HOST]).enable_dns_rebinding_protection is True


def test_parse_hosts_splits_commas_and_drops_blanks():
    assert parse_hosts(f" {CLOUD_HOST} , other.run.app,") == [CLOUD_HOST, "other.run.app"]


def test_parse_hosts_of_empty_string_is_empty():
    assert parse_hosts("") == []
