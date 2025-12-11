# ===============================================
# main.py — Tender Comparison API (A-Variant Safe Mode)
# ===============================================

import os
import zipfile
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from typing import List
from openai import OpenAI
import PyPDF2
import mammoth

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Comparison Engine — A Variant",
    version="1.0",
    description="Safe mode: text trimming to avoid context overflow."
)

# ======================================================
#   TEKSTA TĪRĪTĀJS
# ======================================================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip()

# Limita izmērs (A-variantam pietiek)
MAX_TEXT = 30000


def trim(text: str) -> str:
    """Apgriež tekstu līdz 30 000 simboliem, lai nepieļautu GPT konteksta pārsniegšanu."""
    if len(text) > MAX_TEXT:
        return text[:MAX_TEXT]
    return text

# ======================================================
#   FAILU EKSTRAKTORI
# ======================================================

def extract_pdf(path: str) -> str:
    try:
        text = ""
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() or ""
        return clean(text)
    except:
        return ""


def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
            return clean(result.value)
    except:
        return ""


def extract_zip(path: str) -> str:
    combined = ""
    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():

            if name.endswith("/"):
                continue

            # izvelkam failu
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(z.read(name))
                tmp_path = tmp.name

            if name.lower().endswith(".pdf"):
                combined += extract_pdf(tmp_path)

            elif name.lower().endswith(".docx"):
                combined += extract_docx(tmp_path)

            os.unlink(tmp_path)

    return combined

# ======================================================
#   AI FUNKCIJAS (AR TRIMMING)
# ======================================================

def ai_parse_requirements(text: str) -> str:

    text = trim(text)

    prompt = f"""
Extract key requirements from this document and return JSON:
{{
  "summary": "...",
  "requirements": [...],
  "key_points": [...],
  "risks": [...]
}}
TEXT:
{text}
"""

    response = client.responses.create(
        model="gpt-4o",
        input=prompt
    )

    return response.output_text


def ai_compare(requirements: str, candidate: str) -> str:

    requirements = trim(requirements)
    candidate = trim(candidate)

    prompt = f"""
Compare the candidate document with the requirements.
Return JSON:
{{
  "match_score": 0-100,
  "status": "GREEN | YELLOW | RED",
  "matched_requirements": [...],
  "missing_requirements": [...],
  "risks": [...],
  "summary": "..."
}}

REQUIREMENTS:
{requirements}

CANDIDATE:
{candidate}
"""

    response = client.responses.create(
        model="gpt-4o",
        input=prompt
    )

    return response.output_text

# ======================================================
#   GALVENĀ API /compare_files
# ======================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    full_req_text = ""

    # 1) Ekstrahējam prasības
    for f in requirements:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        name = f.filename.lower()

        if name.endswith(".pdf"):
            full_req_text += extract_pdf(p)
        elif name.endswith(".docx"):
            full_req_text += extract_docx(p)
        elif name.endswith(".zip"):
            full_req_text += extract_zip(p)
        else:
            raise HTTPException(400, f"Unsupported file: {name}")

        os.unlink(p)

    if not full_req_text.strip():
        return {"error": "No readable text in requirements."}

    # GPT prasību analīze
    req_json = ai_parse_requirements(full_req_text)

    # 2) Kandidātu analīze
    results = []

    for f in candidates:

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        if not f.filename.lower().endswith(".zip"):
            raise HTTPException(400, "Candidate must be ZIP.")

        cand_text = extract_zip(p)
        os.unlink(p)

        if not cand_text.strip():
            results.append({
                "candidate": f.filename,
                "error": "Empty or unreadable ZIP"
            })
            continue

        eval_json = ai_compare(req_json, cand_text)

        results.append({
            "candidate": f.filename,
            "analysis": eval_json
        })

    # 3) Gala rezultāts
    return {
        "status": "ok",
        "requirements_structured": req_json,
        "candidate_analysis": results
    }
