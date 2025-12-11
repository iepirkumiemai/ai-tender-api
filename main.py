import os
import zipfile
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

import mammoth
from pdfminer.high_level import extract_text


# ================================================================
#   HELPERS — CLEAN TEXT
# ================================================================
def clean(t: str) -> str:
    if not t:
        return ""
    return t.replace("\x00", "").strip()


# ================================================================
#   EXTRACTORS — PDF, DOCX, TXT, EDOC, ZIP
# ================================================================
def extract_pdf(path: str) -> str:
    try:
        return clean(extract_text(path))
    except Exception:
        return ""


def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
            return clean(result.value)
    except Exception:
        return ""


def extract_txt(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return clean(f.read())
    except Exception:
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

                # Temporarily extract inner file
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(z.read(name))
                    inner_path = tmp.name

                name_low = name.lower()

                if name_low.endswith(".pdf"):
                    combined += extract_pdf(inner_path)
                elif name_low.endswith(".docx"):
                    combined += extract_docx(inner_path)
                elif name_low.endswith(".txt"):
                    combined += extract_txt(inner_path)
                elif name_low.endswith(".edoc"):
                    combined += extract_edoc(inner_path)

                os.unlink(inner_path)
    except:
        pass

    return combined


# ================================================================
#   UNIVERSAL EXTRACTOR — CHOOSES CORRECT HANDLER
# ================================================================
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


# ================================================================
#   GPT — STRUCTURE REQUIREMENTS
# ================================================================
def gpt_structure_requirements(text: str) -> dict:
    prompt = f"""
You are a tender document analyst. Read the tender REQUIREMENTS and return STRICT JSON.

REQUIREMENTS TEXT:
{text}

RETURN JSON EXACTLY IN THIS FORMAT:
{{
  "requirements_list": [...],
  "key_points": [...],
  "risks": [...],
  "summary": "..."
}}
"""

    try:
        response = client.responses.create(
            model="gpt-4.1-turbo",
            input=[{"role": "user", "content": prompt}]
        )
        output = response.output_text
        return output
    except Exception as e:
        return {"error": str(e)}


# ================================================================
#   GPT — COMPARE CANDIDATE
# ================================================================
def gpt_compare_candidate(requirements_json: str, candidate_text: str) -> dict:
    prompt = f"""
Compare the CANDIDATE DOCUMENT with the structured REQUIREMENTS.

REQUIREMENTS JSON:
{requirements_json}

CANDIDATE TEXT:
{candidate_text}

RETURN STRICT JSON:
{{
  "match_score": 0-100,
  "status": "GREEN | YELLOW | RED",
  "met": [...],
  "missing": [...],
  "risks": [...],
  "summary": "..."
}}
"""

    try:
        response = client.responses.create(
            model="gpt-4.1-turbo",
            input=[{"role": "user", "content": prompt}]
        )
        return response.output_text
    except Exception as e:
        return {"error": str(e)}


# ================================================================
#   FASTAPI INIT
# ================================================================
app = FastAPI(
    title="AI Tender Engine — Full Analysis",
    version="9.0",
    description="Full tender requirement extraction + AI comparison (PDF, DOCX, TXT, ZIP, EDOC)"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "engine": "9.0", "mode": "full"}


# ================================================================
#   MAIN ENDPOINT — FULL AI ANALYSIS
# ================================================================
@app.post("/compare_files")
async def compare_files(
    requirements: UploadFile = File(...),
    candidates: UploadFile = File(...)
):
    # ----------------------------
    # 1) Extract Requirements
    # ----------------------------
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await requirements.read())
        req_path = tmp.name

    req_text = extract_any(req_path, requirements.filename)
    os.unlink(req_path)

    if not req_text.strip():
        raise HTTPException(400, "Could not extract text from requirements file.")

    structured_req = gpt_structure_requirements(req_text)

    # ----------------------------
    # 2) Extract Candidate ZIP
    # ----------------------------
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await candidates.read())
        cand_path = tmp.name

    cand_text = extract_any(cand_path, candidates.filename)
    os.unlink(cand_path)

    if not cand_text.strip():
        return {"error": "Candidate file unreadable or empty."}

    comparison = gpt_compare_candidate(structured_req, cand_text)

    # ----------------------------
    # 3) FINAL JSON
    # ----------------------------
    return {
        "status": "OK",
        "requirements_structured": structured_req,
        "candidate_analysis": comparison
    }
