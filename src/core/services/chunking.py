"""Text chunking for RAG ingestion (Phase 1.D). Pure functions, no I/O."""


def chunk_markdown(text: str, chunk_size: int = 800, chunk_overlap: int = 100) -> list[str]:
    """Split Markdown text into overlapping chunks along paragraph boundaries.

    Splits on blank-line-separated paragraphs first (so a heading stays
    attached to the section that follows rather than being cut mid-sentence),
    then greedily packs paragraphs into chunks up to `chunk_size` characters.
    Each new chunk after the first carries the last `chunk_overlap`
    characters of the previous chunk, so a fact near a chunk boundary is
    not only visible in one chunk.

    Args:
        text: The full document text.
        chunk_size: Maximum characters per chunk (a single paragraph longer
            than this is kept whole rather than split mid-sentence).
        chunk_overlap: Characters of trailing context carried into the next
            chunk. Must be smaller than chunk_size.

    Returns:
        A list of chunk strings, in document order. Empty if `text` has no
        non-blank content.
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if not current or len(candidate) <= chunk_size:
            current = candidate
            continue

        chunks.append(current)
        overlap_tail = current[-chunk_overlap:] if chunk_overlap else ""
        current = f"{overlap_tail}\n\n{paragraph}" if overlap_tail else paragraph

    if current:
        chunks.append(current)

    return chunks
