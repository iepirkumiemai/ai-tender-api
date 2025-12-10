# ===============================================
# main.py — Tender Comparison API v11.1 (FINAL)
# ===============================================

import os
import io
import zipfile
import tempfile
from datetime import datetime
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from typing import List
import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

# -----------------------------------------------
# OPENAI CLIENT
# -----------------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -----------------------------------------------
# FASTAPI INIT
# -----------------------------------------------
app = FastAPI(
    title="AI Tender Comparison Engine",
    version="11.1",
    description="Uploads requirement files + candidate ZIP archives, compares them with AI and generates a downloadable PDF report."
)

# -----------------------------------------------
# CLEAN UTIL
# -----------------------------------------------
def clean(text: str) -> str:
    return text.replace("\x00", "").strip()


# =================================================
# FILE EXTRACTORS
# =================================================

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


# =================================================
# AI — REQUIREMENT PARSER
# =================================================

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
Document text:
{text}
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# =================================================
# AI — CANDIDATE COMPARISON
# =================================================

def compare_candidate_ai(requirements: str, candidate_text: str) -> str:
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


# =================================================
# PDF GENERATOR (MAKET: Nr.1)
# =================================================

def generate_pdf(requirements_text, requirements_struct, candidate_file, candidate_text, ai_eval_json):

    os.makedirs("/tmp/pdf_reports/", exist_ok=True)

    filename = f"vertējums_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    full_path = f"/tmp/pdf_reports/{filename}"

    c = canvas.Canvas(full_path, pagesize=A4)
    width, height = A4

    # -------------------
    # TITLE PAGE
    # -------------------
    c.setFont("Helvetica-Bold", 24)
    c.drawString(40, height - 80, "Iepirkuma tehniskais vērtējums")

    c.setFont("Helvetica", 12)
    c.drawString(40, height - 120, f"Datums: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    c.drawString(40, height - 140, f"Versija: 11.1")
    c.drawString(40, height - 160, f"Kandidāta fails: {candidate_file}")

    c.showPage()

    # -------------------
    # REQUIREMENTS SECTION
    # -------------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, height - 50, "1. Iepirkuma prasības")

    c.setFont("Helvetica", 10)
    text_object = c.beginText(40, height - 80)
    text_object.textLines(requirements_text[:5000])  # preview
    c.drawText(text_object)

    c.showPage()

    # -------------------
    # CANDIDATE TEXT
    # -------------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, height - 50, "2. Kandidāta dokumenti")

    c.setFont("Helvetica", 10)
    text_object = c.beginText(40, height - 80)
    text_object.textLines(candidate_text[:5000])
    c.drawText(text_object)

    c.showPage()

    # -------------------
    # AI EVALUATION
    # -------------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, height - 50, "3. AI tehniskais salīdzinājums")

    c.setFont("Helvetica", 10)
    text_object = c.beginText(40, height - 80)
    text_object.textLines(ai_eval_json)
    c.drawText(text_object)

    c.showPage()

    c.save()
    return full_path, filename


# =================================================
# MAIN ENDPOINT — /compare_files
# =================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # -------------------------
    # 1) EXTRACT REQUIREMENTS
    # -------------------------
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
            raise HTTPException(400, f"Unsupported requirement file: {name}")

        os.unlink(p)

    if not req_text.strip():
        raise HTTPException(400, "No readable requirement text.")

    req_struct = parse_requirements_ai(req_text)

    # -------------------------
    # 2) PROCESS CANDIDATES
    # -------------------------

    reports = []

    for f in candidates:

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        name = f.filename.lower()

        if not name.endswith(".zip"):
            raise HTTPException(400, "Candidate must be ZIP.")

        cand_text = extract_zip(p)
        os.unlink(p)

        if not cand_text.strip():
            reports.append({"candidate": name, "error": "empty candidate"})
            continue

        ai_eval = compare_candidate_ai(req_struct, cand_text)

        # -------------------------
        # 3) GENERATE PDF
        # -------------------------
        pdf_path, pdf_file = generate_pdf(
            requirements_text=req_text,
            requirements_struct=req_struct,
            candidate_file=f.filename,
            candidate_text=cand_text,
            ai_eval_json=ai_eval
        )

        reports.append({
            "candidate": f.filename,
            "pdf_file": pdf_file,
            "download_url": f"/download_report/{pdf_file}"
        })

    return {
        "status": "OK",
        "reports": reports
    }


# =================================================
# DOWNLOAD ENDPOINT
# =================================================

@app.get("/download_report/{filename}")
async def download_report(filename: str):

    path = f"/tmp/pdf_reports/{filename}"

    if not os.path.exists(path):
        raise HTTPException(404, "PDF not found")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename
    )
