# ===============================================
# main.py — AI Iepirkumi Tender Engine v8.2
# ===============================================

import os
import zipfile
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from typing import List
import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI

# ==============================
#  OPENAI klienta inicializācija
# ==============================
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Iepirkumi — Tender Comparison Engine",
    version="8.2",
    description="Uploads requirement documents + candidate ZIP files and performs GPT-4.1 tender analysis."
)

# ===============================================
# Helper: Teksta tīrīšana
# ===============================================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip()

# ===============================================
# PDF EXTRACTOR
# ===============================================

def extract_pdf(path: str) -> str:
    try:
        return clean(extract_text(path))
    except:
        return ""

# ===============================================
# DOCX EXTRACTOR
# ===============================================

def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
            return clean(result.value)
    except:
        return ""

# ===============================================
# EDOC EXTRACTOR
# ===============================================

def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith(".xml") or name.endswith(".txt"):
                    try:
                        text += clean(z.read(name).decode(errors="ignore"))
                    except:
                        pass
    except:
        pass
    return text

# ===============================================
# ZIP EXTRACTOR (drošais režīms)
# ===============================================

def extract_zip(path: str) -> str:
    combined = ""

    try:
        with zipfile.ZipFile(path, "r") as z:

            for name in z.namelist():

                if name.endswith("/"):
                    continue

                # saglabā īslaicīgi
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(z.read(name))
                    tmp_path = tmp.name

                lower = name.lower()

                if lower.endswith(".pdf"):
                    combined += extract_pdf(tmp_path)

                elif lower.endswith(".docx"):
                    combined += extract_docx(tmp_path)

                elif lower.endswith(".edoc"):
                    combined += extract_edoc(tmp_path)

                elif lower.endswith(".zip"):
                    combined += extract_zip(tmp_path)

                os.unlink(tmp_path)

    except Exception as e:
        print("ZIP error:", e)

    return combined


# ===============================================
# AI — GPT-4.1 prasību struktūras ģenerēšana
# ===============================================

def parse_requirements_ai(text: str) -> str:
    prompt = f"""
Extract and structure these requirement documents logically and return JSON.

Required JSON structure:
{{
  "requirements": [...],
  "summary": "...",
  "key_points": [...],
  "risks": [...]
}}

Document text:
{text}
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ===============================================
# AI — GPT-4.1 kandidāta salīdzinājums
# ===============================================

def compare_candidate_ai(requirements_json: str, candidate_text: str) -> str:
    prompt = f"""
Compare this candidate document with the tender requirements.

Return JSON with structure:
{{
  "match_score": 0-100,
  "status": "GREEN | YELLOW | RED",
  "matched_requirements": [...],
  "missing_requirements": [...],
  "risks": [...],
  "summary": "..."
}}

REQUIREMENTS JSON:
{requirements_json}

CANDIDATE TEXT:
{candidate_text}
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ======================================================
#   POST ENDPOINT: /compare_files
# ======================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # -------------------------------
    # 1) EXTRACT REQUIREMENT FILES
    # -------------------------------
    full_req_text = ""

    for f in requirements:
        data = await f.read()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            path = tmp.name

        name = f.filename.lower()

        if name.endswith(".pdf"):
            full_req_text += extract_pdf(path)
        elif name.endswith(".docx"):
            full_req_text += extract_docx(path)
        elif name.endswith(".edoc"):
            full_req_text += extract_edoc(path)
        elif name.endswith(".zip"):
            full_req_text += extract_zip(path)
        else:
            raise HTTPException(400, f"Unsupported requirement file: {name}")

        os.unlink(path)

    if not full_req_text.strip():
        raise HTTPException(400, "No readable text found in requirements.")

    # AI prasību struktūra
    requirements_json = parse_requirements_ai(full_req_text)


    # -------------------------------
    # 2) EXTRACT + ANALYZE CANDIDATES
    # -------------------------------
    candidate_results = []

    for f in candidates:

        data = await f.read()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            path = tmp.name

        name = f.filename.lower()

        if not name.endswith(".zip"):
            raise HTTPException(400, f"Candidate file must be ZIP: {name}")

        candidate_text = extract_zip(path)
        os.unlink(path)

        if not candidate_text.strip():
            candidate_results.append({
                "candidate": f.filename,
                "status": "RED",
                "error": "Empty or unreadable candidate ZIP."
            })
            continue

        # AI salīdzināšana
        evaluation = compare_candidate_ai(requirements_json, candidate_text)

        candidate_results.append({
            "candidate": f.filename,
            "evaluation": evaluation
        })


    # -------------------------------
    # 3) FINAL RESPONSE
    # -------------------------------
    return {
        "status": "OK",
        "requirements_parsed": requirements_json,
        "candidates": candidate_results
    }
