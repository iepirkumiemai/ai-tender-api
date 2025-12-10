# chunker.py — Text chunking engine for Tender Engine v6.0

from config import (
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    DEBUG_MODE,
    log
)


def chunk_text(text: str) -> list[str]:
    """
    Splits text into overlapping chunks for AI processing.
    """

    if not text:
        return []

    text = text.strip()

    if DEBUG_MODE:
        log(f"Chunking text of length {len(text)}")

    chunks = []
    start = 0
    length = len(text)

    while start < length:

        end = start + CHUNK_SIZE
        chunk = text[start:end]

        # Try to cut at sentence boundary if possible
        if end < length:
            last_period = chunk.rfind(".")
            last_newline = chunk.rfind("\n")

            cut_pos = max(last_period, last_newline)

            if cut_pos > CHUNK_SIZE * 0.6:
                chunk = chunk[:cut_pos + 1]
                end = start + cut_pos + 1

        chunk = chunk.strip()

        if chunk:
            chunks.append(chunk)
            if DEBUG_MODE:
                log(f"Created chunk len={len(chunk)}")

        # Move start forward with overlap
        start = end - CHUNK_OVERLAP
        if start < 0:
            start = 0

    log(f"Chunking complete: {len(chunks)} chunks generated.")
    return chunks
