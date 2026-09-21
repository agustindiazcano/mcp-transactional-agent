"""Unit tests for src.core.services.chunking.chunk_markdown."""
import pytest

from src.core.services.chunking import chunk_markdown


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n\n   ") == []


def test_single_short_paragraph_returns_one_chunk() -> None:
    text = "Refunds are issued within 30 days of purchase."
    assert chunk_markdown(text, chunk_size=800, chunk_overlap=100) == [text]


def test_paragraphs_within_chunk_size_are_merged() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunk_markdown(text, chunk_size=800, chunk_overlap=100)
    assert len(chunks) == 1
    assert "First paragraph." in chunks[0]
    assert "Third paragraph." in chunks[0]


def test_splits_when_exceeding_chunk_size() -> None:
    para_a = "A" * 50
    para_b = "B" * 50
    text = f"{para_a}\n\n{para_b}"
    chunks = chunk_markdown(text, chunk_size=60, chunk_overlap=10)
    assert len(chunks) == 2
    assert para_a in chunks[0]
    assert para_b in chunks[1]


def test_overlap_carries_tail_of_previous_chunk_into_next() -> None:
    para_a = "A" * 50
    para_b = "B" * 50
    text = f"{para_a}\n\n{para_b}"
    chunks = chunk_markdown(text, chunk_size=60, chunk_overlap=10)
    # The last 10 chars of chunk 1 (all "A"s) should reappear at the start of chunk 2.
    assert chunks[1].startswith("A" * 10)


def test_oversized_single_paragraph_kept_whole_not_split_mid_sentence() -> None:
    long_paragraph = ("word " * 300).strip()  # far longer than chunk_size
    chunks = chunk_markdown(long_paragraph, chunk_size=100, chunk_overlap=20)
    assert len(chunks) == 1
    assert chunks[0] == long_paragraph


def test_chunk_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValueError, match="chunk_overlap must be smaller than chunk_size"):
        chunk_markdown("some text", chunk_size=100, chunk_overlap=100)


def test_real_refund_policy_document_produces_multiple_chunks() -> None:
    from pathlib import Path

    policy_path = Path(__file__).parents[2] / "docs" / "policies" / "refund_policy.md"
    text = policy_path.read_text(encoding="utf-8")

    chunks = chunk_markdown(text, chunk_size=400, chunk_overlap=50)

    assert len(chunks) > 1
    # No chunk should silently balloon past chunk_size + a paragraph's worth of overlap.
    assert all(len(c) < 800 for c in chunks)
    # Known section headers from the real document should survive chunking somewhere.
    joined = "\n".join(chunks)
    assert "Standard Refund Window" in joined
    assert "Refund Amount Limits and Fraud Flags" in joined
