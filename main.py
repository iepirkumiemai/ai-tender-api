# ======================================================
# main.py — AI Tender Analyzer (GPT-4o Stable Version)
# ======================================================

import os
import zipfile
import tempfile
from typing import List

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

from openai import OpenAI
import mammoth
from PyPDF2 import PdfReader

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Engine",
    version="1.0",
    description="Tender requirement vs candidate ZIP comparison using GPT-4o"
)

# ======================================================
#   TEXT UTIL
# ======================================================

def clean(text: str) -> str:
    if not text:
        return ""
    return text.replace("\x00", "").strip()


# ======================================================
#   FILE EXTRACTORS
# ======================================================

def extract_pdf(path: str) -> str:
    try:
        reader = PdfReader(path)
        text = ""
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


def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith(".xml") or name.endswith(".txt"):
                    data = z.read(name).decode("utf-8", errors="ignore")
                    text += clean(data)
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

    return combined


# ======================================================
#   GPT-4o REQUIREMENT PARSING
# ======================================================

def ai_parse_requirements(text: str) -> dict:
    prompt = f"""
Extract and structure the tender REQUIREMENTS from this document.

Return JSON ONLY with this structure:

{{
  "requirements": [...],
  "summary": "...",
  "key_points": [...],
  "risks": [...]
}}

Document:
{text}
"""

    response = client.responses.create(
        model="gpt-4o",
        input=prompt
    )

    return response.output_text


# ======================================================
#   GPT-4o CANDIDATE EVALUATION
# ======================================================

def ai_compare(requirements: str, candidate: str) -> dict:
    prompt = f"""
Compare the CANDIDATE DOCUMENT with the REQUIREMENTS.

Return JSON ONLY:

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
#   MAIN ENDPOINT — /compare_files
# ======================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # ------------------------------------
    # 1) Extract REQUIREMENT documents
    # ------------------------------------

    req_text = ""

    for f in requirements:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        fn = f.filename.lower()

        if fn.endswith(".pdf"):
            req_text += extract_pdf(p)
        elif fn.endswith(".docx"):
            req_text += extract_docx(p)
        elif fn.endswith(".edoc"):
            req_text += extract_edoc(p)
        elif fn.endswith(".zip"):
            req_text += extract_zip(p)
        else:
            raise HTTPException(400, f"Unsupported requirement file: {fn}")

        os.unlink(p)

    if not req_text.strip():
        return {"error": "No readable text found in requirement files."}

    requirements_json = ai_parse_requirements(req_text)

    # ------------------------------------
    # 2) Extract CANDIDATE ZIP files
    # ------------------------------------

    results = []

    for f in candidates:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        fn = f.filename.lower()

        if not fn.endswith(".zip"):
            raise HTTPException(400, f"Candidate must be a ZIP archive: {fn}")

        cand_text = extract_zip(p)
        os.unlink(p)

        if not cand_text.strip():
            results.append({
                "candidate": f.filename,
                "error": "Empty or unreadable candidate ZIP"
            })
            continue

        analysis_json = ai_compare(requirements_json, cand_text)

        results.append({
            "candidate": f.filename,
            "analysis": analysis_json
        })

    # ------------------------------------
    # 3) Return final JSON
    # ------------------------------------

    return {
        "status": "ok",
        "requirements_structured": requirements_json,
        "candidate_analysis": results
    }
