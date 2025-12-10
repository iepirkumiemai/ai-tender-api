# ===============================================
# main.py — Tender Comparison Engine v12
# Stabils Unicode PDF + AI salīdzināšana
# ===============================================

import os
import zipfile
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from typing import List
import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI
from fpdf import FPDF

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="12.0",
    description="Uploads requirement files + candidate ZIP archives, compares them and generates a downloadable PDF."
)

# ===============================================
# HELPERS
# ===============================================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip()

# ===============================================
# FILE EXTRACTORS
# ===============================================

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

# ===============================================
# AI — GPT-4.1 REQUIREMENTS
# ===============================================

def parse_requirements_ai(text: str) -> str:
    prompt = f"""
Izvelc prasības no dokumentiem un atgriez JSON formātā:

{{
  "prasības": [...],
  "kopsavilkums": "...",
  "riski": [...],
  "svarīgākie_punkti": [...]
}}

Dokuments:
{text}
"""
    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )
    return response.output_text

# ===============================================
# AI — GPT-4.1 CANDIDATE EVALUATION
# ===============================================

def compare_candidate_ai(requirements: str, candidate_text: str) -> str:
    prompt = f"""
Salīdzini kandidātu ar prasībām.

Atgriez JSON:

{{
  "status": "zaļš | dzeltens | sarkans",
  "score": 0-100,
  "atbilst": [...],
  "neatbilst": [...],
  "vajag_pārbaudīt": [...],
  "kopsavilkums": "..."
}}

PRASĪBAS:
{requirements}

KANDIDĀTA DOKUMENTS:
{candidate_text}
"""
    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )
    return response.output_text

# ===============================================
# PDF GENERATOR (UNICODE)
# ===============================================

def generate_pdf_report(result: dict) -> str:
    pdf = FPDF()
    pdf.add_page()

    # --- Add Unicode font ---
    FONT_PATH = "/app/NotoSans-Regular.ttf"

    if not os.path.exists(FONT_PATH):
        # create a fallback font
        FONT_PATH = "/tmp/NotoSans-Regular.ttf"
        with open(FONT_PATH, "wb") as f:
            f.write(open("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "rb").read())

    pdf.add_font("Noto", "", FONT_PATH, uni=True)
    pdf.set_font("Noto", size=14)

    pdf.cell(0, 10, "Vērtējums", ln=True)

    pdf.set_font("Noto", size=11)
    pdf.multi_cell(0, 7, result["summary"])

    # candidate list
    pdf.ln(5)
    pdf.set_font("Noto", size=12)
    pdf.cell(0, 10, "Kandidāti:", ln=True)

    for cand in result["candidates"]:
        pdf.set_font("Noto", size=11)
        pdf.multi_cell(
            0, 6,
            f"{cand['name']} — status: {cand['status']} (score: {cand['score']})"
        )
        pdf.ln(2)

    out_path = f"/tmp/report_{os.getpid()}.pdf"
    pdf.output(out_path)
    return out_path

# ===============================================
# MAIN ENDPOINT — /compare_files_with_pdf
# ===============================================

@app.post("/compare_files_with_pdf")
async def compare_files_with_pdf(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # 1) Extract requirement text
    req_text = ""
    for f in requirements:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        if f.filename.lower().endswith(".pdf"):
            req_text += extract_pdf(p)
        elif f.filename.lower().endswith(".docx"):
            req_text += extract_docx(p)
        elif f.filename.lower().endswith(".edoc"):
            req_text += extract_edoc(p)
        elif f.filename.lower().endswith(".zip"):
            req_text += extract_zip(p)

        os.unlink(p)

    if not req_text.strip():
        raise HTTPException(400, "Nevar nolasīt prasību dokumentus.")

    req_struct = parse_requirements_ai(req_text)

    # 2) Extract + analyze candidates
    results = []
    for f in candidates:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        candidate_text = extract_zip(p)
        os.unlink(p)

        if not candidate_text.strip():
            results.append({"name": f.filename, "status": "sarkans", "summary": "Tukšs fails", "score": 0})
            continue

        ai_eval = compare_candidate_ai(req_struct, candidate_text)

        results.append({
            "name": f.filename,
            **eval(ai_eval)  # Convert string JSON → dict
        })

    # 3) Build combined summary for PDF
    summary = "Kopsavilkums par vērtējumu"

    full_result = {
        "summary": summary,
        "candidates": results
    }

    # 4) Generate PDF
    pdf_path = generate_pdf_report(full_result)

    # 5) Railway download link
    download_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/download/{os.path.basename(pdf_path)}"

    return {
        "status": "OK",
        "pdf_url": download_url,
        "raw": full_result
    }
