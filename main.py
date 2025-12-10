# ===============================================
# main.py — Tender Comparison API v9.0
# ===============================================

import os
import zipfile
import tempfile
from typing import List

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI

# -----------------------------------------------
# OPENAI CLIENT
# -----------------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="9.0",
    description="Uploads multiple requirement files + multiple candidate ZIPs and compares them using GPT-4.1"
)

# ======================================================
#   CLEAN TEXT
# ======================================================
def clean(text: str) -> str:
    return text.replace("\x00", "").strip()

# ======================================================
#   FILE EXTRACTION HELPERS
# ======================================================

def extract_pdf(path: str) -> str:
    try:
        return clean(extract_text(path))
    except:
        return ""

def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f).value
            return clean(result)
    except:
        return ""

def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith(".xml") or name.endswith(".txt"):
                    text += clean(z.read(name).decode(errors="ignore"))
    except:
        pass
    return text

def extract_zip(path: str) -> str:
    combined = ""
    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():

            if name.endswith("/"):
                continue

            # Write internal file temporarily
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(z.read(name))
                tmp_path = tmp.name

            # Detect file type
            lname = name.lower()
            if lname.endswith(".pdf"):
                combined += extract_pdf(tmp_path)
            elif lname.endswith(".docx"):
                combined += extract_docx(tmp_path)
            elif lname.endswith(".edoc"):
                combined += extract_edoc(tmp_path)
            elif lname.endswith(".zip"):
                combined += extract_zip(tmp_path)

            os.unlink(tmp_path)

    return combined

# ======================================================
#   AI — REQUIREMENT PARSER
# ======================================================

def parse_requirements_ai(text: str) -> str:

    prompt = f"""
You will extract and structure the following requirement documents.

Return STRICT JSON:

{{
  "requirements": [...],
  "summary": "...",
  "key_points": [...],
  "risks": [...]
}}

Document text:
{text}
"""

    r = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return r.output_text

# ======================================================
#   AI — CANDIDATE COMPARISON (GREEN/YELLOW/RED)
# ======================================================

def ai_compare_engine(requirements_json: str, candidate_text: str) -> str:

    prompt = f"""
Compare REQUIREMENTS with CANDIDATE DOCUMENT.

Return STRICT JSON:

{{
  "match_score": 0-100,
  "status": "GREEN | YELLOW | RED",
  "matched_requirements": [...],
  "missing_requirements": [...],
  "risks": [...],
  "summary": "..."
}}

STATUS RULES:
- match_score >= 90 → "GREEN"
- 60 ≤ match_score < 90 → "YELLOW"
- match_score < 60 → "RED"

=====================
REQUIREMENTS JSON:
=====================
{requirements_json}

=====================
CANDIDATE DOCUMENT:
=====================
{candidate_text}
"""

    r = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return r.output_text


# ======================================================
#   MAIN ENDPOINT — /compare_files
# ======================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # --------------------------------------------------
    # 1) Extract requirement documents
    # --------------------------------------------------
    full_req_text = ""

    for f in requirements:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        fname = f.filename.lower()

        if fname.endswith(".pdf"):
            full_req_text += extract_pdf(p)
        elif fname.endswith(".docx"):
            full_req_text += extract_docx(p)
        elif fname.endswith(".edoc"):
            full_req_text += extract_edoc(p)
        elif fname.endswith(".zip"):
            full_req_text += extract_zip(p)
        else:
            raise HTTPException(400, f"Unsupported requirement file: {fname}")

        os.unlink(p)

    if not full_req_text.strip():
        return {"error": "No readable text extracted from requirements."}

    # Run GPT-4.1 requirement parser
    requirements_structured = parse_requirements_ai(full_req_text)

    # --------------------------------------------------
    # 2) Extract candidates
    # --------------------------------------------------
    results = []

    for f in candidates:

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        fname = f.filename.lower()

        if not fname.endswith(".zip"):
            raise HTTPException(400, f"Candidate must be ZIP: " + fname)

        candidate_text = extract_zip(p)
        os.unlink(p)

        if not candidate_text.strip():
            results.append({
                "candidate": f.filename,
                "status": "RED",
                "reason": "Candidate ZIP contained no readable text."
            })
            continue

        # Run GPT-4.1 comparison engine
        evaluation = ai_compare_engine(requirements_structured, candidate_text)

        results.append({
            "candidate": f.filename,
            "evaluation": evaluation
        })

    # --------------------------------------------------
    # 3) Final response
    # --------------------------------------------------
    return {
        "status": "OK",
        "requirements_parsed": requirements_structured,
        "candidates": results
    }
