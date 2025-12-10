# ============================================================
# main.py — AI Tender Comparison Engine v2.0
# ============================================================

import os
import zipfile
import tempfile
from typing import List

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI

# ------------------------------------------------------------
# OpenAI klienta inicializācija
# ------------------------------------------------------------

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="2.0",
    description="Uploads multiple requirement files + candidate ZIP archives, extracts text and performs AI comparison using GPT-4.1."
)

# ============================================================
# HELPERS — Teksta attīrīšana
# ============================================================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip()


# ============================================================
# FAILU EKSTRAKTORI
# ============================================================

def extract_pdf(path: str) -> str:
    try:
        return clean(extract_text(path))
    except:
        return ""


def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
            return clean(result.value)
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

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(z.read(name))
                tmp_path = tmp.name

            if name.lower().endswith(".pdf"):
                combined += extract_pdf(tmp_path)

            elif name.lower().endswith(".docx"):
                combined += extract_docx(tmp_path)

            elif name.lower().endswith(".edoc"):
                combined += extract_edoc(tmp_path)

            elif name.lower().endswith(".zip"):
                combined += extract_zip(tmp_path)

            os.unlink(tmp_path)

    return combined


# ============================================================
# AI FUNKCIJAS — GPT-4.1 analīze
# ============================================================

def ai_parse_requirements(text: str) -> dict:
    """Analizē prasību dokumentus un sadala kategorijās."""
    prompt = f"""
Extract and structure the tender REQUIREMENT DOCUMENTS.

Return JSON exactly in this structure:

{{
  "requirements": [...], 
  "mandatory_requirements": [...],
  "technical_requirements": [...],
  "risk_flags": [...],
  "summary": "..."
}}

--- REQUIREMENT DOCUMENT TEXT (FULL) ---
{text}
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


def ai_compare_candidate(requirements_json: str, candidate_text: str) -> dict:
    """AI salīdzina kandidātu ar prasību dokumentiem."""
    prompt = f"""
Compare the CANDIDATE DOCUMENT with the REQUIREMENTS.

Return JSON in this exact structure:

{{
  "match_score": 0-100,
  "status": "GREEN | YELLOW | RED",
  "matched_requirements": [...],
  "missing_requirements": [...],
  "risks": [...],
  "summary": "..."
}}

--- STRUCTURED REQUIREMENTS JSON ---
{requirements_json}

--- CANDIDATE DOCUMENT ---
{candidate_text}
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ============================================================
# GALVENĀ API METODE — /compare_files
# ============================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # ======================================================
    # 1) REQUIREMENT DOKUMENTU EKSTRAKCIJA
    # ======================================================

    req_text = ""

    for f in requirements:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        name = f.filename.lower()

        if name.endswith(".pdf"):
            req_text += extract_pdf(p)
        elif name.endswith(".docx"):
            req_text += extract_docx(p)
        elif name.endswith(".edoc"):
            req_text += extract_edoc(p)
        elif name.endswith(".zip"):
            req_text += extract_zip(p)
        else:
            raise HTTPException(400, f"Unsupported requirement file type: {name}")

        os.unlink(p)

    if not req_text.strip():
        raise HTTPException(400, "Requirement documents contain no readable text.")

    # AI struktūrizē prasības
    structured_requirements = ai_parse_requirements(req_text)


    # ======================================================
    # 2) KANDIDĀTU ZIP EKSTRAKCIJA UN AI SALĪDZINĀŠANA
    # ======================================================

    candidate_results = []

    for f in candidates:

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        if not f.filename.lower().endswith(".zip"):
            raise HTTPException(400, f"Candidate must be ZIP: {f.filename}")

        cand_text = extract_zip(p)
        os.unlink(p)

        if not cand_text.strip():
            candidate_results.append({
                "candidate": f.filename,
                "status": "RED",
                "reason": "Unreadable or empty candidate archive."
            })
            continue

        # AI salīdzina prasības ar kandidātu
        evaluation = ai_compare_candidate(structured_requirements, cand_text)

        candidate_results.append({
            "candidate": f.filename,
            "evaluation": evaluation
        })


    # ======================================================
    # 3) FINĀLAIS JSON REZULTĀTS
    # ======================================================

    return {
        "status": "OK",
        "requirements_parsed": structured_requirements,
        "candidates": candidate_results
    }
