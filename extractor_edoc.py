# extractor_edoc.py — EDOC text extractor for Tender Engine v6.0

import xml.etree.ElementTree as ET
from config import log

def extract_edoc(path: str) -> str:
    """
    Extracts text from EDOC (XML-based) documents.
    """
    log(f"Parsing EDOC: {path}")

    try:
        # Try XML parse
        tree = ET.parse(path)
        root = tree.getroot()
        text = " ".join(root.itertext())
        return text
    except Exception:
        pass

    try:
        # Try reading as plain text fallback
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        log(f"EDOC extraction error: {e}")
        return ""
