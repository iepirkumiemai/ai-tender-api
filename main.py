# ===============================================
# main.py — Tender Comparison API v8.0
# ===============================================

import os
import zipfile
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import JSONResponse
from typing import List
import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="8.0",
    description="Uploads multiple requirement files + multiple candidate ZIP archives and compares them using GPT-4.1."
)

# ======================================================
#   TEXT CLEANER
# ======================================================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip()


# ======================================================
#   FILE EXTRACTORS
# ======================================================

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


# ======================================================
#   AI — GPT-4.1 REQUIREMENT PARSER
# ======================================================

def parse_requirements_ai(text: str) -> dict:
    prompt = f"""
Extract and structure these requirement documents.

Return JSON:
{{
  "requirements": [...],
  "summary": "...",
  "key_points": [...],
  "risk_flags": [...]
}}
Document text:
{text}
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ======================================================
#   AI — GPT-4.1 CANDIDATE EVALUATION
# ======================================================

def compare_candidate_ai(requirements: str, candidate_text: str) -> dict:
    prompt = f"""
Compare this candidate document against the requirements.

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

CANDIDATE DOCUMENT:
{candidate_text}
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ======================================================
#   MAIN ENDPOINT — /compare_files
# ======================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # ======================================================
    #   1) EXTRACT REQUIREMENTS
    # ======================================================

    full_req_text = ""

    for f in requirements:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        name = f.filename.lower()

        if name.endswith(".pdf"):
            full_req_text += extract_pdf(p)
        elif name.endswith(".docx"):
            full_req_text += extract_docx(p)
        elif name.endswith(".edoc"):
            full_req_text += extract_edoc(p)
        elif name.endswith(".zip"):
            full_req_text += extract_zip(p)
        else:
            raise HTTPException(400, f"Unsupported requirement file: {name}")

        os.unlink(p)

    if not full_req_text.strip():
        return {"error": "No readable text in requirements."}

    # Parse requirements using GPT-4.1
    req_structured = parse_requirements_ai(full_req_text)


    # ======================================================
    #   2) EXTRACT CANDIDATES
    # ======================================================

    candidate_results = []

    for f in candidates:

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        name = f.filename.lower()

        if not name.endswith(".zip"):
            raise HTTPException(400, f"Candidate must be ZIP: {name}")

        candidate_text = extract_zip(p)
        os.unlink(p)

        if not candidate_text.strip():
            candidate_results.append({
                "candidate": f.filename,
                "status": "RED",
                "reason": "Empty or unreadable candidate.",
            })
            continue

        # GPT-4.1 comparison
        ai_eval = compare_candidate_ai(req_structured, candidate_text)

        candidate_results.append({
            "candidate": f.filename,
            "evaluation": ai_eval
        })


    # ======================================================
    #   3) FINAL RESPONSE
    # ======================================================

    return {
        "status": "OK",
        "requirements_parsed": req_structured,
        "candidates": candidate_results
    }
