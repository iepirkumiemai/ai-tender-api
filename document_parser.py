import zipfile
import tempfile
from pathlib import Path

class DocumentParserError(Exception):
    pass


class DocumentParser:

    @staticmethod
    def extract(path: Path):
        """
        Ekstrahē tekstu no:
        - TXT
        - PDF
        - DOCX
        - ZIP (meklē tikai .txt / .md)
        
        Atgriež dict:
        {
            "filename": ...,
            "type": ...,
            "text": ...
        }
        """

        suffix = path.suffix.lower()

        # ============================
        # TXT fails
        # ============================
        if suffix == ".txt":
            return {
                "filename": path.name,
                "type": "txt",
                "text": path.read_text(errors="ignore")
            }

        # ============================
        # PDF fails
        # ============================
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)

                return {
                    "filename": path.name,
                    "type": "pdf",
                    "text": text,
                }
            except Exception as e:
                raise DocumentParserError(f"PDF extraction failed: {e}")

        # ============================
        # DOCX fails
        # ============================
        if suffix == ".docx":
            try:
                import docx
                doc = docx.Document(str(path))
                text = "\n".join(p.text for p in doc.paragraphs)

                return {
                    "filename": path.name,
                    "type": "docx",
                    "text": text,
                }
            except Exception as e:
                raise DocumentParserError(f"DOCX extraction failed: {e}")

        # ============================
        # ZIP fails
        # ============================
        if suffix == ".zip":
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    with zipfile.ZipFile(path, "r") as z:
                        z.extractall(tmpdir)

                    extracted = list(Path(tmpdir).rglob("*"))
                    text = ""

                    for f in extracted:
                        if f.suffix.lower() in [".txt", ".md"]:
                            try:
                                text += f.read_text(errors="ignore") + "\n"
                            except:
                                pass

                    return {
                        "filename": path.name,
                        "type": "zip",
                        "text": text,
                    }

            except Exception as e:
                raise DocumentParserError(f"ZIP extraction failed: {e}")

        # ============================
        # Nepazīstams formāts
        # ============================
        raise DocumentParserError(f"Unsupported file type: {suffix}")
