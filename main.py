# ===============================================
# main.py — Tender Comparison API v12 (PDF + Unicode)
# ===============================================

import os
import zipfile
import tempfile
import base64

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from typing import List

import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI

from fpdf import FPDF

# ======================================================
#   OPENAI CLIENT
# ======================================================

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ======================================================
#   INIT FASTAPI
# ======================================================

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="12.0",
    description="Uploads requirement documents + candidate ZIP archives and generates comparison report + PDF."
)

# ======================================================
#   EMBEDDED UNICODE FONT (FREESANS)
# ======================================================

# Base64 FreeSans.ttf (truncated here — actual encoded font included below)
FREESANS_BASE64 = """
AAEAAAASAQAABAAgR0RFRrRCsIIAAjSsAAACYkdQT1OxB3AEAAI1WAAA
...
"""  # <-- Te ieliksim pilno fontu 280–300 KB apjomā

FONT_PATH = "/tmp/FreeSans.ttf"

def ensure_font_exists():
    if not os.path.exists(FONT_PATH):
        with open(FONT_PATH, "wb") as f:
            f.write(base64.b64decode(FREESANS_BASE64))


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

    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():

                if name.endswith("/"):
                    continue

                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(z.read(name))
                    tmp_path = tmp.name

                filename = name.lower()

                if filename.endswith(".pdf"):
                    combined += extract_pdf(tmp_path)

                elif filename.endswith(".docx"):
                    combined += extract_docx(tmp_path)

                elif filename.endswith(".edoc"):
                    combined += extract_edoc(tmp_path)

                elif filename.endswith(".zip"):
                    combined += extract_zip(tmp_path)

                os.unlink(tmp_path)

    except:
        pass

    return combined


# ======================================================
#   AI — REQUIREMENT PARSING
# ======================================================

def parse_requirements_ai(text: str) -> str:
    prompt = f"""
Izvelc prasības un strukturē tās.

Atgriez JSON formātu:

{{
  "prasibas": [...],
  "kopsavilkums": "...",
  "riski": [...],
  "prioritates": [...]
}}

Dokuments:
{text}
"""

    r = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return r.output_text


# ======================================================
#   AI — CANDIDATE COMPARISON
# ======================================================

def compare_candidate_ai(requirements: str, candidate_text: str) -> str:
    prompt = f"""
Salīdzini kandidāta dokumentu ar prasībām.

Atgriez JSON formātu:

{{
  "score": 0-100,
  "status": "ZAĻŠ | DZELTENS | SARKANS",
  "atbilst": [...],
  "neatbilst": [...],
  "riski": [...],
  "kopsavilkums": "..."
}}

PRASĪBAS:
{requirements}

KANDIDĀTS:
{candidate_text}
"""

    r = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return r.output_text


# ======================================================
#   PDF GENERATOR
# ======================================================

def generate_pdf(requirements_json: str, candidate_results: list) -> str:
    ensure_font_exists()

    pdf = FPDF()
    pdf.add_page()

    # Load Unicode font
    pdf.add_font("FreeSans", "", FONT_PATH, uni=True)
    pdf.set_font("FreeSans", "", 16)

    # Title
    pdf.set_text_color(0, 60, 120)
    pdf.cell(0, 10, "VĒRTĒJUMS", ln=True, align="C")

    pdf.ln(5)

    # Requirements section
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("FreeSans", "", 12)
    pdf.multi_cell(0, 7, f"Prasību kopsavilkums:\n{requirements_json}")

    pdf.ln(5)

    # Candidates
    for cand in candidate_results:

        pdf.set_font("FreeSans", "B", 13)
        pdf.set_text_color(0, 0, 0)
        pdf.multi_cell(0, 7, f"Kandidāts: {cand['candidate']}")

        status = cand["eval"]["status"]

        if status == "ZAĻŠ":
            pdf.set_text_color(0, 150, 0)
        elif status == "DZELTENS":
            pdf.set_text_color(220, 160, 0)
        else:
            pdf.set_text_color(200, 0, 0)

        pdf.set_font("FreeSans", "", 12)
        pdf.multi_cell(0, 7, f"STATUS: {status}")

        pdf.set_text_color(0, 0, 0)
        pdf.multi_cell(0, 7, cand["eval"]["kopsavilkums"])

        pdf.ln(4)

    # Save output
    out_path = "/tmp/vertējums.pdf"
    pdf.output(out_path)

    return out_path


# ======================================================
#   MAIN ENDPOINT
# ======================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # ----------------------
    # Extract requirements
    # ----------------------

    req_text = ""

    for f in requirements:
        data = await f.read()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
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
            raise HTTPException(400, f"Nepareizs prasību fails: {name}")

        os.unlink(p)

    if not req_text.strip():
        raise HTTPException(400, "Nav tekstu, ko analizēt prasībās.")

    req_struct = parse_requirements_ai(req_text)

    # ----------------------
    # Extract & evaluate candidates
    # ----------------------

    cand_results = []

    for f in candidates:
        data = await f.read()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            p = tmp.name

        name = f.filename.lower()

        if not name.endswith(".zip"):
            raise HTTPException(400, f"Kandidātam jābūt ZIP: {name}")

        cand_text = extract_zip(p)
        os.unlink(p)

        if not cand_text.strip():
            cand_results.append({
                "candidate": f.filename,
                "eval": {
                    "status": "SARKANS",
                    "kopsavilkums": "Kandidāta fails ir tukšs vai nesalasāms."
                }
            })
            continue

        ai_eval = compare_candidate_ai(req_struct, cand_text)

        cand_results.append({
            "candidate": f.filename,
            "eval": eval(ai_eval)
        })

    # ----------------------
    # Generate PDF
    # ----------------------

    pdf_path = generate_pdf(req_struct, cand_results)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="vertejums.pdf"
    )
