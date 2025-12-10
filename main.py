# ===============================================
# main.py — Tender Comparison API v12 (PDF-ready)
# ===============================================

import os
import zipfile
import tempfile
from typing import List

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse

import mammoth
from pdfminer.high_level import extract_text
from fpdf import FPDF
from openai import OpenAI


# ======================================================
# OPENAI CLIENT
# ======================================================

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ======================================================
# FASTAPI INIT
# ======================================================

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="12.0",
    description="Uploads requirement documents + candidate ZIP files, compares them using GPT-4.1 and returns a PDF report."
)


# ======================================================
# CLEAN TEXT UTILITY
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
#   AI — REQUIREMENT PARSER (GPT-4.1)
# ======================================================

def parse_requirements_ai(text: str) -> dict:

    prompt = f"""
Izvelc prasības no dokumentiem un strukturē tās JSON formātā.

Atgriez JSON:

{{
  "prasības": [...],
  "kopsavilkums": "...",
  "galvenie_punkti": [...],
  "riski": [...]
}}

Teksts:
{text}
    """

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ======================================================
#   AI — CANDIDATE COMPARISON (GPT-4.1)
# ======================================================

def compare_candidate_ai(requirements_structured: str, candidate_text: str) -> dict:

    prompt = f"""
Salīdzini kandidāta dokumentus ar prasībām.

Atgriez JSON formātā:

{{
  "status": "zaļš | dzeltens | sarkans",
  "atbilst": [...],
  "neatbilst": [...],
  "jāpārbauda_manuāli": [...],
  "kopsavilkums": "..."
}}

PRASĪBAS:
{requirements_structured}

KANDIDĀTS:
{candidate_text}
    """

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ======================================================
# PDF GENERATOR (Helvetica, Railway-safe)
# ======================================================

def generate_pdf_report(result_json: dict) -> str:

    base_dir = "/tmp/reports"
    os.makedirs(base_dir, exist_ok=True)

    pdf_path = f"{base_dir}/vertējums.pdf"

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=12)

    pdf.set_font("Helvetica", size=16)
    pdf.cell(0, 10, "Vērtējums", ln=True)

    pdf.set_font("Helvetica", size=11)

    # vienkārši izdrukā visu JSON kā tekstu
    for key, value in result_json.items():
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 8, f"{key}:")

        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, str(value))
        pdf.ln(2)

    pdf.output(pdf_path)

    return pdf_path


# ======================================================
#   MAIN ENDPOINT — /compare_files_with_pdf
# ======================================================

@app.post("/compare_files_with_pdf")
async def compare_files_with_pdf(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # -------------------------------------
    # 1) EXTRACT REQUIREMENTS
    # -------------------------------------

    req_text = ""

    for f in requirements:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        filename = f.filename.lower()

        if filename.endswith(".pdf"):
            req_text += extract_pdf(p)
        elif filename.endswith(".docx"):
            req_text += extract_docx(p)
        elif filename.endswith(".edoc"):
            req_text += extract_edoc(p)
        elif filename.endswith(".zip"):
            req_text += extract_zip(p)
        else:
            raise HTTPException(400, f"Nepareizs prasību faila tips: {filename}")

        os.unlink(p)

    if not req_text.strip():
        raise HTTPException(400, "Prasību failos nav nolasāma teksta.")

    requirements_structured = parse_requirements_ai(req_text)


    # -------------------------------------
    # 2) PROCESS CANDIDATES
    # -------------------------------------

    candidate_results = []

    for f in candidates:

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        filename = f.filename.lower()

        if not filename.endswith(".zip"):
            raise HTTPException(400, f"Kandidāta fails nav ZIP: {filename}")

        candidate_text = extract_zip(p)
        os.unlink(p)

        if not candidate_text.strip():
            candidate_results.append({
                "kandidāts": f.filename,
                "status": "sarkans",
                "kļūda": "Tukšs vai nenolasāms ZIP."
            })
            continue

        ai_eval = compare_candidate_ai(requirements_structured, candidate_text)

        candidate_results.append({
            "kandidāts": f.filename,
            "vērtējums": ai_eval
        })


    # -------------------------------------
    # 3) BUILD FINAL JSON
    # -------------------------------------

    result = {
        "prasību_analīze": requirements_structured,
        "kandidātu_rezultāti": candidate_results
    }

    # -------------------------------------
    # 4) GENERATE PDF
    # -------------------------------------

    pdf_path = generate_pdf_report(result)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="vertējums.pdf"
    )
