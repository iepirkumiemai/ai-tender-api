# ===========================
# PDF, DOCX, TXT, XML TEKSTA EKSTRAKCIJA
# ===========================

from pdfminer.high_level import extract_text as pdf_extract
from docx import Document
from lxml import etree

def extract_text_from_pdf(path: str) -> str:
    try:
        return pdf_extract(path)
    except Exception as e:
        return f"[PDF ERROR] {e}"

def extract_text_from_docx(path: str) -> str:
    try:
        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs]
        return "\n".join(paragraphs)
    except Exception as e:
        return f"[DOCX ERROR] {e}"

def extract_text_from_txt(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        return f"[TXT ERROR] {e}"

def extract_xml_structure(path: str) -> str:
    """
    EDOC XML struktūras nolasīšana saprotamā teksta formā.
    """
    try:
        tree = etree.parse(path)
        root = tree.getroot()
        return etree.tostring(root, pretty_print=True, encoding="unicode")
    except Exception as e:
        return f"[XML ERROR] {e}"


def extract_text_by_type(path: str, file_type: str) -> str:
    """
    Vienotais interfeiss dokumentu teksta nolasīšanai.
    """
    if file_type == "pdf":
        return extract_text_from_pdf(path)

    if file_type == "docx":
        return extract_text_from_docx(path)

    if file_type == "txt":
        return extract_text_from_txt(path)

    if file_type == "edoc" and path.lower().endswith(".xml"):
        return extract_xml_structure(path)

    return "[UNSUPPORTED FILE TYPE]"
