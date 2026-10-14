"""Text chunking for RAG ingestion (Phase 1.D). Pure functions, no I/O."""


def _is_heading(paragraph: str) -> bool:
    """True for a Markdown heading line (`#`, `##`, ...)."""
    return paragraph.startswith("#") and "\n" not in paragraph


def chunk_markdown(text: str, chunk_size: int = 800, chunk_overlap: int = 100) -> list[str]:
    """Split Markdown text into overlapping chunks along paragraph boundaries.

    Splits on blank-line-separated paragraphs first (so a heading stays
    attached to the section that follows rather than being cut mid-sentence),
    then greedily packs paragraphs into chunks up to `chunk_size` characters.
    A heading is never left at the end of a chunk: it moves to the start of
    the next one, so it always travels with the rules under it. Each new
    chunk after the first carries the last `chunk_overlap` characters of the
    previous chunk, so a fact near a chunk boundary is not only visible in
    one chunk.

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
    current: list[str] = []

    for paragraph in paragraphs:
        candidate = "\n\n".join([*current, paragraph])
        if not current or len(candidate) <= chunk_size:
            current.append(paragraph)
            continue

        carried: list[str] = []
        if len(current) > 1 and _is_heading(current[-1]):
            carried = [current.pop()]

        finished = "\n\n".join(current)
        chunks.append(finished)
        overlap_tail = finished[-chunk_overlap:] if chunk_overlap else ""
        current = [overlap_tail, *carried, paragraph] if overlap_tail else [*carried, paragraph]

    if current:
        chunks.append("\n\n".join(current))

    return chunks
