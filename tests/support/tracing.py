"""Capture Langfuse spans in memory: the real SDK, no network.

`trace_exporter` (registered in tests/conftest.py) installs a Langfuse client
that exports to an InMemorySpanExporter for one test, then disables tracing
again. Outside that fixture, tracing is off for the whole test run.
"""
from collections.abc import Iterator
from itertools import count
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.core import tracing
from src.core.config import Settings

_key_ids = count()


def tracing_settings(**overrides: Any) -> Settings:
    """Settings with tracing on and placeholder keys, plus `overrides`."""
    base: dict[str, Any] = {
        "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
        "LANGFUSE_SECRET_KEY": "sk-lf-test",
        "LANGFUSE_BASE_URL": "https://us.cloud.langfuse.com",
        "LANGFUSE_TRACING_ENABLED": True,
        "LANGFUSE_TRACING_ENVIRONMENT": "test",
    }
    return Settings(**{**base, **overrides})


def unique_public_key() -> str:
    """A fresh key per client: the SDK keeps one client per public key, and a
    reused key would silently keep the previous test's exporter."""
    return f"pk-lf-test-{next(_key_ids)}"


@pytest.fixture
def trace_exporter() -> Iterator[InMemorySpanExporter]:
    """Enable tracing into memory for one test."""
    exporter = InMemorySpanExporter()
    cfg = tracing_settings(LANGFUSE_PUBLIC_KEY=unique_public_key())
    client = tracing.build_client(cfg, span_exporter=exporter)
    tracing.configure_tracing(client, public_key=cfg.LANGFUSE_PUBLIC_KEY)
    yield exporter
    client.shutdown()
    tracing.configure_tracing(None)


def finished_spans(exporter: InMemorySpanExporter) -> dict[str, ReadableSpan]:
    """Flush, then return the exported spans by name (last one wins)."""
    tracing.flush_tracing()
    return {span.name: span for span in exporter.get_finished_spans()}


def span_attr(span: ReadableSpan, key: str) -> Any:
    """One exported attribute of `span` (None when absent)."""
    assert span.attributes is not None
    return span.attributes.get(key)


def is_child_of(child: ReadableSpan, parent: ReadableSpan) -> bool:
    """True when `child` is directly nested under `parent`."""
    return child.parent is not None and child.parent.span_id == parent.context.span_id
