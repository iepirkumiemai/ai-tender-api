# ================================================================
# main.py — Tender Engine v11 (PDF Download Edition)
# ================================================================

import os
import zipfile
import tempfile
import base64

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from typing import List

import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI
from fpdf import FPDF


# ================================================================
# OpenAI Client
# ================================================================
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="11.0",
    description="Requirement extraction + candidate ZIP evaluation + PDF output"
)


# ================================================================
# FONT — DejaVuSans encoded in Base64 (Unicode support)
# ================================================================

DEJAVU_BASE64 = """
AAEAAAASAQAABAAgR0RFRrRCsIIAAj0AAA ... VERY LONG BASE64 FONT ... AAA==
""".strip()

FONT_PATH = "/tmp/dejavu.ttf"

if not os.path.exists(FONT_PATH):
    with open(FONT_PATH, "wb") as f:
        f.write(base64.b64decode(DEJAVU_BASE64))


# ================================================================
# Helper — Clean text
# ================================================================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip()


# ================================================================
# Extractors
# ================================================================

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
                temp_path = tmp.name

            if name.lower().endswith(".pdf"):
                combined += extract_pdf(temp_path)

            elif name.lower().endswith(".docx"):
                combined += extract_docx(temp_path)

            elif name.lower().endswith(".edoc"):
                combined += extract_edoc(temp_path)

            elif name.lower().endswith(".zip"):
                combined += extract_zip(temp_path)

            os.unlink(temp_path)

    return combined


# ================================================================
# AI — Requirement parsing
# ================================================================

def parse_requirements_ai(text: str) -> str:

    prompt = f"""
Extract and structure these requirement documents.

Return JSON:
{{
  "requirements": [...],
  "summary": "...",
  "key_points": [...],
  "risk_flags": [...]
}}

DOCUMENT:
{text}
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ================================================================
# AI — Candidate comparison
# ================================================================

def compare_candidate_ai(requirements_structured: str, candidate_text: str) -> str:

    prompt = f"""
Compare this candidate against structured requirements.

Return JSON:
{{
  "match_score": 0-100,
  "status": "GREEN | YELLOW | RED",
  "matched": [...],
  "missing": [...],
  "risks": [...],
  "summary": "..."
}}

REQUIREMENTS:
{requirements_structured}

CANDIDATE:
{candidate_text}
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ================================================================
# PDF GENERATOR
# ================================================================

def generate_pdf(requirements: str, results: list) -> str:

    pdf_path = "/tmp/tender_report.pdf"

    pdf = FPDF()
    pdf.add_page()

    # Add font
    pdf.add_font("DejaVu", "", FONT_PATH, uni=True)
    pdf.set_font("DejaVu", size=12)

    pdf.multi_cell(0, 8, "AI Tender Comparison Report")
    pdf.ln(4)

    pdf.multi_cell(0, 6, "=== REQUIREMENTS ===")
    pdf.multi_cell(0, 6, str(requirements))
    pdf.ln(6)

    pdf.multi_cell(0, 6, "=== CANDIDATE RESULTS ===")

    for c in results:
        pdf.ln(4)
        pdf.multi_cell(0, 6, f"Candidate: {c['candidate']}")
        pdf.multi_cell(0, 6, str(c['evaluation']))

    pdf.output(pdf_path)

    return pdf_path


# ================================================================
# ENDPOINT: /compare_files
# ================================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # -------------------------
    # REQUIREMENTS EXTRACTION
    # -------------------------

    full_requirements_text = ""

    for f in requirements:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        name = f.filename.lower()

        if name.endswith(".pdf"):
            full_requirements_text += extract_pdf(p)
        elif name.endswith(".docx"):
            full_requirements_text += extract_docx(p)
        elif name.endswith(".edoc"):
            full_requirements_text += extract_edoc(p)
        elif name.endswith(".zip"):
            full_requirements_text += extract_zip(p)
        else:
            raise HTTPException(400, f"Unsupported requirement file: {name}")

        os.unlink(p)

    if not full_requirements_text.strip():
        raise HTTPException(status_code=400, detail="No readable requirement text found.")

    req_structured = parse_requirements_ai(full_requirements_text)


    # -------------------------
    # CANDIDATES EXTRACTION
    # -------------------------

    candidate_results = []

    for f in candidates:

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        if not f.filename.lower().endswith(".zip"):
            raise HTTPException(400, f"Candidate must be ZIP: {f.filename}")

        candidate_text = extract_zip(p)
        os.unlink(p)

        if not candidate_text.strip():
            candidate_results.append({
                "candidate": f.filename,
                "evaluation": "EMPTY FILE — RED"
            })
            continue

        ai_eval = compare_candidate_ai(req_structured, candidate_text)

        candidate_results.append({
            "candidate": f.filename,
            "evaluation": ai_eval
        })

    # -------------------------
    # PDF GENERATION
    # -------------------------

    pdf_path = generate_pdf(req_structured, candidate_results)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="tender_report.pdf"
    )
