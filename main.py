# ===============================================
# main.py — Tender Comparison Engine v1.0 (Stable Upload Version)
# ===============================================

import os
import zipfile
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import JSONResponse
from typing import List
import mammoth
from pdfminer.high_level import extract_text

# ======================================================
# FASTAPI INIT
# ======================================================

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="1.0-upload-stable",
    description="Uploads requirement files + candidate ZIP archives. File extraction ready. AI analysis added later."
)


# ======================================================
# HELPERS
# ======================================================

def clean(text: str) -> str:
    if not text:
        return ""
    return text.replace("\x00", "").strip()


# ======================================================
# FILE EXTRACTORS
# ======================================================

def extract_pdf(path: str) -> str:
    try:
        return clean(extract_text(path))
    except:
        return ""


def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            text = mammoth.extract_raw_text(f).value
            return clean(text)
    except:
        return ""


def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith(".xml") or name.endswith(".txt"):
                    try:
                        raw = z.read(name).decode(errors="ignore")
                        text += clean(raw)
                    except:
                        continue
    except:
        pass
    return text


def extract_zip(path: str) -> str:
    combined = ""

    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():

            if name.endswith("/"):
                continue

            # Save temp file
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(z.read(name))
                tmp_path = tmp.name

            # Detect type
            low = name.lower()

            if low.endswith(".pdf"):
                combined += extract_pdf(tmp_path)

            elif low.endswith(".docx"):
                combined += extract_docx(tmp_path)

            elif low.endswith(".edoc"):
                combined += extract_edoc(tmp_path)

            elif low.endswith(".zip"):
                combined += extract_zip(tmp_path)

            # Delete temp file
            os.unlink(tmp_path)

    return combined


# ======================================================
# MAIN ENDPOINT — /compare_files (WITH REAL UPLOAD INPUTS)
# ======================================================

@app.post("/compare_files")
async def compare_files(
    dummy: str = Form("x"),                     # fixes Swagger bug
    requirements: List[UploadFile] = File(..., description="Requirement documents (PDF, DOCX, EDOC, ZIP)"),
    candidates: List[UploadFile] = File(..., description="Candidate ZIP archives")
):

    # ======================================================
    # 1) EXTRACT ALL REQUIREMENTS
    # ======================================================

    full_requirements_text = ""

    for file in requirements:

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await file.read())
            p = tmp.name

        name = file.filename.lower()

        if name.endswith(".pdf"):
            full_requirements_text += extract_pdf(p)
        elif name.endswith(".docx"):
            full_requirements_text += extract_docx(p)
        elif name.endswith(".edoc"):
            full_requirements_text += extract_edoc(p)
        elif name.endswith(".zip"):
            full_requirements_text += extract_zip(p)
        else:
            raise HTTPException(400, f"Unsupported requirement file: {file.filename}")

        os.unlink(p)

    if not full_requirements_text.strip():
        return {"error": "No readable text extracted from requirement files."}


    # ======================================================
    # 2) EXTRACT ALL CANDIDATES
    # ======================================================

    extracted_candidates = []

    for file in candidates:

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await file.read())
            p = tmp.name

        name = file.filename.lower()

        if not name.endswith(".zip"):
            raise HTTPException(400, f"Candidate must be ZIP: {file.filename}")

        candidate_text = extract_zip(p)
        os.unlink(p)

        extracted_candidates.append({
            "filename": file.filename,
            "text_length": len(candidate_text),
            "text_preview": candidate_text[:500]
        })

    # ======================================================
    # RETURN — READY FOR AI LATER
    # ======================================================

    return {
        "status": "OK",
        "requirements_extracted": len(full_requirements_text),
        "requirements_preview": full_requirements_text[:500],
        "candidates_processed": extracted_candidates
    }
