# extractor_pdf.py — PDF text extractor for Tender Engine v6.0

from pdfminer.high_level import extract_text
from config import log

def extract_pdf(path: str) -> str:
    """
    Extracts text from a PDF file using pdfminer.
    """
    log(f"Parsing PDF: {path}")
    try:
        text = extract_text(path)
        if not text:
            log("PDF extraction returned empty text.")
        return text or ""
    except Exception as e:
        log(f"PDF extraction error: {e}")
        return ""
