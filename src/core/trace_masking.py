"""Redact sensitive values from Langfuse spans before they leave the process.

Runs as the Langfuse client's `mask_otel_spans` hook, at export time, over
every string attribute -- so it also covers the prompts and completions the
LangChain callback records, not only what this code sets explicitly.

The rules follow the MCP audit log (src/mcp_server/security/audit.py): a
`user_id` is never exported raw. It is replaced by a stable pseudonym, so
traces can still be grouped per user without revealing who the user is.
Claim text is kept, since it is what a reviewer needs to judge a trace, but
emails and long digit runs (phone and card numbers) inside it are redacted.

Pure functions only: the hook runs on the exporter's worker thread and must
stay fast and free of I/O.
"""

import hashlib
import re

from langfuse.types import (
    MaskOtelSpansParams,
    MaskOtelSpansResult,
    OtelSpanIdentifier,
    OtelSpanPatch,
)

EMAIL_REDACTED = "[EMAIL_REDACTED]"
NUMBER_REDACTED = "[NUMBER_REDACTED]"

_PSEUDONYM_PREFIX = "usr_"
_PSEUDONYM = re.compile(r"^usr_[0-9a-f]{12}$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 9 to 19 digits, optionally separated by spaces, dashes or brackets: phone
# and card numbers. Dates (8 digits), UUID segments (bounded by letters or
# dashes) and decimals (a dot next to a digit, e.g. the guard's 0.99895...
# score) fall outside it; a sentence-ending dot does not.
_LONG_NUMBER = re.compile(r"(?<![\w.-])\+?\(?\d(?:[ ()-]{0,2}\d){8,18}(?![\w-]|\.\d)")
# A "user_id" JSON field at any escaping depth: the judges' prompt embeds the
# claim as JSON, and the callback serializes that prompt as JSON again.
_USER_ID_FIELD = re.compile(r'(\\*"user_id\\*"\s*:\s*\\*")([^"\\]*)(\\*")')


def pseudonymize_user_id(user_id: str) -> str:
    """Return a stable, non-reversible stand-in for `user_id`.

    Idempotent, so a value that is already a pseudonym is left as it is.
    """
    if _PSEUDONYM.match(user_id):
        return user_id
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
    return f"{_PSEUDONYM_PREFIX}{digest}"


def mask_text(text: str) -> str:
    """Redact emails and phone/card numbers, and pseudonymize user_id fields."""
    masked = _USER_ID_FIELD.sub(
        lambda m: f"{m.group(1)}{pseudonymize_user_id(m.group(2))}{m.group(3)}", text
    )
    masked = _EMAIL.sub(EMAIL_REDACTED, masked)
    return _LONG_NUMBER.sub(NUMBER_REDACTED, masked)


def mask_otel_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult | None:
    """Langfuse `mask_otel_spans` hook: patch only the attributes that change.

    Returns None when nothing in the batch is sensitive, leaving it untouched.
    """
    patches: dict[OtelSpanIdentifier, OtelSpanPatch | None] = {}
    for identifier, span in params.spans.items():
        replacements: dict[str, str] = {}
        for key, value in span.attributes.items():
            if isinstance(value, str):
                masked = mask_text(value)
                if masked != value:
                    replacements[key] = masked
        if replacements:
            patches[identifier] = OtelSpanPatch(set_attributes=replacements)
    if not patches:
        return None
    return MaskOtelSpansResult(span_patches=patches)
