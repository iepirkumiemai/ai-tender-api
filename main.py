# ================================================================
# main.py — Tender Engine v11.1 (Helvetica PDF Download Edition)
# ================================================================

import os
import zipfile
import tempfile

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
    version="11.1",
    description="Extracts requirements + evaluates candidates + generates PDF (Helvetica)"
)


# ================================================================
# Helper: Clean text
# ================================================================
def clean(text: str) -> str:
    return text.replace("\x00", "").strip()


# ================================================================
# File extractors
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

            lname = name.lower()

            if lname.endswith(".pdf"):
                combined += extract_pdf(temp_path)
            elif lname.endswith(".docx"):
                combined += extract_docx(temp_path)
            elif lname.endswith(".edoc"):
                combined += extract_edoc(temp_path)
            elif lname.endswith(".zip"):
                combined += extract_zip(temp_path)

            os.unlink(temp_path)

    return combined


# ================================================================
# AI — Requirement Parser
# ================================================================
def parse_requirements_ai(text: str) -> str:

    prompt = f"""
Extract and structure the requirement documents.

Return JSON:
{{
  "summary": "...",
  "key_points": [...],
  "risks": [...],
  "requirements": [...]
}}

DOCUMENT:
{text}
"""

    r = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return r.output_text


# ================================================================
# AI — Candidate Comparison
# ================================================================
def compare_candidate_ai(requirements_structured: str, candidate_text: str) -> str:

    prompt = f"""
Compare structured REQUIREMENTS with CANDIDATE.

Return JSON:
{{
  "match_score": 0-100,
  "status": "ZAĻŠ | DZELTENS | SARKANS",
  "matched": [...],
  "missing": [...],
  "risks": [...],
  "summary": "..."
}}

Rules:
- ZAĻŠ (>= 90)
- DZELTENS (60–89)
- SARKANS (< 60)

REQUIREMENTS:
{requirements_structured}

CANDIDATE:
{candidate_text}
"""

    r = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return r.output_text


# ================================================================
# PDF Generator (Helvetica only)
# ================================================================
def generate_pdf(requirements: str, candidate_results: list) -> str:

    pdf_path = "/tmp/vertejums.pdf"

    pdf = FPDF()
    pdf.add_page()

    # ---------------- HEADER ----------------
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 12, "VĒRTĒJUMS", ln=True, align="C")

    pdf.ln(6)
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(0.7)
    pdf.line(10, 28, 200, 28)
    pdf.ln(10)

    # ---------------- REQUIREMENTS ----------------
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 10, "Prasību kopsavilkums", ln=True)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 6, requirements)
    pdf.ln(8)

    # ---------------- CANDIDATES ----------------
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 10, "Kandidātu vērtējums", ln=True)
    pdf.ln(4)

    for cand in candidate_results:

        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, f"Kandidāts: {cand['candidate']}", ln=True)

        evaluation = cand["evaluation"]

        # ---------------- STATUS COLOR ----------------
        if "ZAĻŠ" in evaluation:
            pdf.set_text_color(0, 150, 0)
            status_text = "STATUS: ZAĻŠ — atbilst prasībām"
        elif "DZELTENS" in evaluation:
            pdf.set_text_color(220, 160, 0)
            status_text = "STATUS: DZELTENS — jāpārbauda manuāli"
        else:
            pdf.set_text_color(200, 0, 0)
            status_text = "STATUS: SARKANS — neatbilst prasībām"

        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 6, status_text, ln=True)

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 5, evaluation)
        pdf.ln(10)

    pdf.output(pdf_path)
    return pdf_path


# ================================================================
# ENDPOINT: /compare_files (returns PDF directly)
# ================================================================
@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # ---------------- EXTRACT REQUIREMENTS ----------------
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
        raise HTTPException(400, "No readable requirement text.")

    structured_requirements = parse_requirements_ai(full_req_text)

    # ---------------- EXTRACT CANDIDATES ----------------
    candidate_results = []

    for f in candidates:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        if not f.filename.lower().endswith(".zip"):
            raise HTTPException(400, "Candidate must be ZIP file.")

        candidate_text = extract_zip(p)
        os.unlink(p)

        if not candidate_text.strip():
            candidate_results.append({
                "candidate": f.filename,
                "evaluation": "SARKANS — tukšs fails"
            })
            continue

        ai_eval = compare_candidate_ai(structured_requirements, candidate_text)

        candidate_results.append({
            "candidate": f.filename,
            "evaluation": ai_eval
        })

    # ---------------- GENERATE PDF ----------------
    pdf_path = generate_pdf(structured_requirements, candidate_results)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="vertejums.pdf"
    )
