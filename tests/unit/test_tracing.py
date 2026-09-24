"""Langfuse tracing wiring, exercised against the real SDK with an in-memory
OpenTelemetry exporter: spans are captured locally, nothing leaves the test.
"""
from unittest.mock import MagicMock

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.core import tracing
from src.core.trace_masking import pseudonymize_user_id
from tests.support.tracing import (
    finished_spans,
    is_child_of,
    span_attr,
    tracing_settings,
    unique_public_key,
)


@pytest.fixture
def exporter(trace_exporter: InMemorySpanExporter) -> InMemorySpanExporter:
    return trace_exporter


# ── Enabling ────────────────────────────────────────────────────────────────


def test_tracing_is_disabled_without_keys():
    assert tracing.is_tracing_enabled(tracing_settings(LANGFUSE_SECRET_KEY="")) is False
    assert tracing.is_tracing_enabled(tracing_settings(LANGFUSE_PUBLIC_KEY="")) is False


def test_tracing_can_be_switched_off_with_keys_present():
    assert tracing.is_tracing_enabled(tracing_settings(LANGFUSE_TRACING_ENABLED=False)) is False


def test_tracing_is_enabled_with_both_keys():
    assert tracing.is_tracing_enabled(tracing_settings()) is True


def test_build_client_applies_environment_and_masking():
    cfg = tracing_settings(LANGFUSE_PUBLIC_KEY=unique_public_key())

    client = tracing.build_client(cfg, span_exporter=InMemorySpanExporter())

    assert isinstance(client, Langfuse)
    assert client._environment == "test"
    client.shutdown()


# ── Disabled: every helper is a safe no-op ──────────────────────────────────


def test_disabled_tracing_yields_a_noop_observation():
    tracing.configure_tracing(None)

    with tracing.observe("scan-prompt-injection", as_type="guardrail") as obs:
        obs.update(output={"status": "clear"})

    assert tracing.langchain_config() == {}


def test_disabled_claim_trace_is_a_noop():
    tracing.configure_tracing(None)

    with tracing.claim_trace("req-1", user_id="u-1", input={"claim_text": "x"}) as root:
        root.update(output={"status": "COMPLETED"})


# ── Enabled: structure of a claim trace ─────────────────────────────────────


def test_claim_trace_is_the_root_with_a_trace_id_derived_from_request_id(exporter):
    with tracing.claim_trace("req-42", user_id="customer-4821", input={"claim_text": "hi"}) as root:
        root.update(output={"status": "COMPLETED"})

    root_span = finished_spans(exporter)["process-claim"]
    assert span_attr(root_span, "langfuse.internal.as_root") is True
    assert f"{root_span.context.trace_id:032x}" == Langfuse.create_trace_id(seed="req-42")
    assert span_attr(root_span, "langfuse.trace.name") == "process-claim"
    assert span_attr(root_span, "user.id") == pseudonymize_user_id("customer-4821")
    assert span_attr(root_span, "langfuse.trace.metadata.request_id") == "req-42"


def test_observations_nest_under_the_claim_trace_with_their_type(exporter):
    with (
        tracing.claim_trace("req-7", user_id="u-7", input={"claim_text": "hi"}),
        tracing.observe("evaluate-proposal", as_type="chain"),
        tracing.observe("run-judge-1", as_type="evaluator") as judge,
    ):
        judge.update(output={"verdict": "APPROVE"})

    spans = finished_spans(exporter)
    root, chain, judge_span = spans["process-claim"], spans["evaluate-proposal"], spans["run-judge-1"]
    assert is_child_of(chain, root)
    assert is_child_of(judge_span, chain)
    assert span_attr(judge_span, "langfuse.observation.type") == "evaluator"
    assert "APPROVE" in span_attr(judge_span, "langfuse.observation.output")


def test_embedding_observation_records_model_and_usage(exporter):
    with tracing.observe(
        "embed-claim", as_type="embedding", model="gemini-embedding-001"
    ) as obs:
        obs.update(usage_details={"input": 12}, metadata={"estimated_usage": True})

    span = finished_spans(exporter)["embed-claim"]
    assert span_attr(span, "langfuse.observation.model.name") == "gemini-embedding-001"
    assert "12" in span_attr(span, "langfuse.observation.usage_details")


def test_trace_content_is_masked_before_export(exporter):
    with tracing.claim_trace(
        "req-9", user_id="u-9", input={"claim_text": "email me at jane@example.com"}
    ):
        pass

    exported_input = span_attr(finished_spans(exporter)["process-claim"], "langfuse.observation.input")
    assert "jane@example.com" not in exported_input
    assert "[EMAIL_REDACTED]" in exported_input


def test_langchain_config_carries_a_langfuse_callback_when_enabled(exporter):
    callbacks = tracing.langchain_config()["callbacks"]

    assert len(callbacks) == 1
    assert type(callbacks[0]).__name__ == "LangchainCallbackHandler"


# ── Failure isolation: tracing never breaks claim processing ────────────────


def test_application_errors_propagate_through_an_observation(exporter):
    with pytest.raises(ValueError, match="boom"), tracing.observe("execute-refund", as_type="tool"):
        raise ValueError("boom")

    span = finished_spans(exporter)["execute-refund"]
    assert span_attr(span, "langfuse.observation.level") == "ERROR"


def test_a_failing_langfuse_client_degrades_to_a_noop():
    broken = MagicMock(spec=Langfuse)
    broken.start_as_current_observation.side_effect = RuntimeError("otel down")
    tracing.configure_tracing(broken)
    try:
        with tracing.observe("run-judge-2", as_type="evaluator") as obs:
            obs.update(output={"verdict": "REJECT"})
        with tracing.claim_trace("req-1", user_id="u-1", input={}) as root:
            root.update(output={})
    finally:
        tracing.configure_tracing(None)


def test_a_failing_update_is_swallowed():
    inner = MagicMock()
    inner.update.side_effect = RuntimeError("serialization failed")

    tracing.TraceObservation(inner).update(output={"x": 1})


def test_shutdown_is_safe_when_disabled():
    tracing.configure_tracing(None)

    tracing.shutdown_tracing()
