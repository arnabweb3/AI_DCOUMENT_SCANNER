# chunker.py
# Splits long text into small pieces (chunks) so we can store them in the vector database

from config import CHUNK_SIZE, CHUNK_OVERLAP


def split_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = text.strip()
    if text == "":
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        # try to cut at a new line or full stop so we don't cut in the middle of a sentence
        if end < len(text):
            last_newline = text.rfind("\n", start, end)
            last_dot = text.rfind(". ", start, end)
            cut = max(last_newline, last_dot)
            if cut > start + chunk_size // 2:
                end = cut + 1

        chunk = text[start:end].strip()
        if chunk != "":
            chunks.append(chunk)

        if end >= len(text):
            break
        # go back a little bit so chunks overlap
        start = end - overlap

    return chunks
