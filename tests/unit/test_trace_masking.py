from types import MappingProxyType

from langfuse.types import MaskOtelSpansParams, OtelSpanData, OtelSpanIdentifier

from src.core.trace_masking import (
    NUMBER_REDACTED,
    mask_otel_spans,
    mask_text,
    pseudonymize_user_id,
)


def _span(attributes: dict[str, object]) -> OtelSpanData:
    return OtelSpanData(
        trace_id="0" * 32,
        span_id="1" * 16,
        parent_span_id=None,
        name="process-claim",
        instrumentation_scope_name="langfuse-sdk",
        instrumentation_scope_version=None,
        attributes=MappingProxyType(attributes),  # type: ignore[arg-type]
        resource_attributes=MappingProxyType({}),
    )


def test_pseudonymize_is_stable_and_hides_the_raw_id():
    first = pseudonymize_user_id("customer-4821")

    assert first == pseudonymize_user_id("customer-4821")
    assert first != pseudonymize_user_id("customer-4822")
    assert first.startswith("usr_")
    assert "4821" not in first


def test_pseudonymize_is_idempotent():
    pseudonym = pseudonymize_user_id("customer-4821")

    assert pseudonymize_user_id(pseudonym) == pseudonym


def test_mask_text_redacts_emails():
    masked = mask_text("Contact me at jane.doe+refunds@example.co.uk please")

    assert "jane.doe" not in masked
    assert "[EMAIL_REDACTED]" in masked


def test_mask_text_redacts_phone_and_card_numbers():
    masked = mask_text("Call +1 (415) 555-0132, card 4111 1111 1111 1111.")

    assert "555-0132" not in masked
    assert "4111" not in masked
    assert masked.count("[NUMBER_REDACTED]") == 2


def test_mask_text_keeps_business_values_readable():
    """Amounts, dates, timestamps and UUID request ids are what a reviewer
    needs to read a trace; none of them may be mistaken for a phone number."""
    text = (
        "Refund 45.50 USD for order ORD-1001 bought 2026-09-24T10:15:00Z, "
        "request 550e8400-e29b-41d4-a716-446655440000, 3 items"
    )

    assert mask_text(text) == text


def test_mask_text_pseudonymizes_user_id_fields_at_any_json_escaping_level():
    plain = '{"user_id": "customer-4821", "amount": 10}'
    escaped = '{\\"user_id\\": \\"customer-4821\\"}'

    pseudonym = pseudonymize_user_id("customer-4821")
    assert mask_text(plain) == f'{{"user_id": "{pseudonym}", "amount": 10}}'
    assert mask_text(escaped) == f'{{\\"user_id\\": \\"{pseudonym}\\"}}'


def test_mask_otel_spans_patches_only_changed_string_attributes():
    identifier = OtelSpanIdentifier(trace_id="0" * 32, span_id="1" * 16)
    span = _span(
        {
            "langfuse.observation.input": '{"claim_text": "mail me at a@b.io"}',
            "langfuse.observation.output": "APPROVE",
            "gen_ai.usage.input_tokens": 120,
        }
    )

    result = mask_otel_spans(params=MaskOtelSpansParams(spans={identifier: span}))

    assert result is not None
    patch = result.span_patches[identifier]
    assert patch.set_attributes == {
        "langfuse.observation.input": '{"claim_text": "mail me at [EMAIL_REDACTED]"}'
    }


def test_mask_otel_spans_returns_none_when_nothing_is_sensitive():
    identifier = OtelSpanIdentifier(trace_id="0" * 32, span_id="1" * 16)
    span = _span({"langfuse.observation.output": "APPROVE"})

    assert mask_otel_spans(params=MaskOtelSpansParams(spans={identifier: span})) is None


def test_mask_text_keeps_long_decimal_fractions():
    """Regression: the guard's probability score has 16 decimals and was
    redacted as a phone number, hiding the guardrail's key output."""
    text = '{"status": "blocked", "score": 0.9989551305770874, "cost": 12.000000001}'

    assert mask_text(text) == text


def test_mask_text_redacts_a_number_that_ends_a_sentence():
    assert mask_text("My card is 4111111111111111.") == f"My card is {NUMBER_REDACTED}."
