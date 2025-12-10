# extractor_zip.py — SAFE ZIP extraction with nested support for Tender Engine v6.0

import os
import zipfile
import tempfile

from config import (
    log,
    MAX_ZIP_FILES,
    MAX_ZIP_DEPTH,
    ALLOWED_EXTENSIONS
)

from extractor_pdf import extract_pdf
from extractor_docx import extract_docx
from extractor_edoc import extract_edoc


# ===============================================================
# Extract TXT safely
# ===============================================================

def extract_txt(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except:
        return ""


# ===============================================================
# MAIN ZIP EXTRACTION
# ===============================================================

def extract_zip(path: str, depth: int = 0):
    """
    Extracts ALL allowed files from ZIP (PDF/DOCX/EDOC/TXT/ZIP nested).
    Returns:
        text (str): full combined text
        files (list): metadata about extracted files
    """

    log(f"Extracting ZIP: {path} | depth={depth}")

    if depth > MAX_ZIP_DEPTH:
        raise ValueError("Nested ZIP depth exceeded allowed limit.")

    files_collected = []
    combined_text = ""

    with zipfile.ZipFile(path, "r") as z:
        namelist = z.namelist()

        if len(namelist) > MAX_ZIP_FILES:
            raise ValueError(
                f"ZIP contains {len(namelist)} files (limit {MAX_ZIP_FILES})"
            )

        for item in namelist:
            log(f"ZIP item: {item}")

            ext = os.path.splitext(item)[1].lower()

            # Skip unsupported files
            if ext not in ALLOWED_EXTENSIONS:
                log(f"Skipping unsupported file: {item}")
                continue

            # Extract the file to a temp path
            tmp_fd, tmp_file = tempfile.mkstemp(suffix=ext)
            os.close(tmp_fd)

            with open(tmp_file, "wb") as out:
                out.write(z.read(item))

            size = os.path.getsize(tmp_file)

            files_collected.append({
                "name": item,
                "size": size,
                "type": ext.replace(".", "")
            })

            # Decide how to extract
            if ext == ".pdf":
                combined_text += extract_pdf(tmp_file)

            elif ext == ".docx":
                combined_text += extract_docx(tmp_file)

            elif ext == ".edoc":
                combined_text += extract_edoc(tmp_file)

            elif ext == ".txt":
                combined_text += extract_txt(tmp_file)

            elif ext == ".zip":
                nested_text, nested_files = extract_zip(tmp_file, depth + 1)
                combined_text += nested_text
                files_collected.extend(nested_files)

    return combined_text, files_collected
