# extractor_docx.py — DOCX text extractor for Tender Engine v6.0

import mammoth
from config import log

def extract_docx(path: str) -> str:
    """
    Extracts text from DOCX using mammoth.
    """
    log(f"Parsing DOCX: {path}")
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
        return result.value or ""
    except Exception as e:
        log(f"DOCX extraction error: {e}")
        return ""
