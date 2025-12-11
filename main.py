import os
import zipfile
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import openai
openai.api_key = os.getenv("OPENAI_API_KEY")

import mammoth
from pdfminer.high_level import extract_text


# ===========================
# TEXT CLEANER
# ===========================
def clean(t: str) -> str:
    if not t:
        return ""
    return t.replace("\x00", "").strip()


# ===========================
# FILE EXTRACTORS
# ===========================
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


def extract_txt(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return clean(f.read())
    except:
        return ""


def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.lower().endswith(".txt") or name.lower().endswith(".xml"):
                    try:
                        text += clean(z.read(name).decode(errors="ignore"))
                    except:
                        pass
    except:
        pass
    return text


def extract_zip(path: str) -> str:
    combined = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue

                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(z.read(name))
                    inner = tmp.name

                name_low = name.lower()

                if name_low.endswith(".pdf"):
                    combined += extract_pdf(inner)
                elif name_low.endswith(".docx"):
                    combined += extract_docx(inner)
                elif name_low.endswith(".txt"):
                    combined += extract_txt(inner)
                elif name_low.endswith(".edoc"):
                    combined += extract_edoc(inner)

                os.unlink(inner)
    except:
        pass

    return combined


def extract_any(path: str, filename: str) -> str:
    name = filename.lower()

    if name.endswith(".pdf"):
        return extract_pdf(path)
    if name.endswith(".docx"):
        return extract_docx(path)
    if name.endswith(".txt"):
        return extract_txt(path)
    if name.endswith(".edoc"):
        return extract_edoc(path)
    if name.endswith(".zip"):
        return extract_zip(path)

    return ""


# ===========================
# GPT FUNCTIONS
# ===========================
def gpt_structure_requirements(text: str):
    prompt = f"""
You are a tender analyzer. Read the requirements and return STRICT JSON:

{{
  "requirements_list": [...],
  "key_points": [...],
  "risks": [...],
  "summary": "..."
}}

REQUIREMENT TEXT:
{text}
"""

    try:
        response = openai.responses.create(
            model="gpt-4.1-turbo",
            input=[{"role": "user", "content": prompt}]
        )
        return response.output_text
    except Exception as e:
        return {"error": str(e)}


def gpt_compare_candidate(requirements_json: str, candidate_text: str):
    prompt = f"""
Compare REQUIREMENTS and CANDIDATE. Return STRICT JSON:

{{
  "match_score": 0-100,
  "status": "GREEN | YELLOW | RED",
  "met": [...],
  "missing": [...],
  "risks": [...],
  "summary": "..."
}}

REQUIREMENTS:
{requirements_json}

CANDIDATE:
{candidate_text}
"""

    try:
        response = openai.responses.create(
            model="gpt-4.1-turbo",
            input=[{"role": "user", "content": prompt}]
        )
        return response.output_text
    except Exception as e:
        return {"error": str(e)}


# ===========================
# FASTAPI APP
# ===========================
app = FastAPI(title="AI Tender Engine", version="9.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "engine": "9.1"}


# ===========================
# MAIN ENDPOINT
# ===========================
@app.post("/compare_files")
async def compare_files(
    requirements: UploadFile = File(...),
    candidates: UploadFile = File(...)
):
    # Requirements
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await requirements.read())
        req_path = tmp.name

    req_text = extract_any(req_path, requirements.filename)
    os.unlink(req_path)

    if not req_text:
        raise HTTPException(400, "Requirements unreadable")

    structured = gpt_structure_requirements(req_text)

    # Candidate ZIP
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await candidates.read())
        cand_path = tmp.name

    cand_text = extract_any(cand_path, candidates.filename)
    os.unlink(cand_path)

    if not cand_text:
        raise HTTPException(400, "Candidate unreadable")

    comparison = gpt_compare_candidate(structured, cand_text)

    return {
        "status": "ok",
        "requirements_structured": structured,
        "candidate_analysis": comparison
    }
