# ===============================================
# main.py — Tender Comparison Engine v12.1
# Stabils PDF ģenerators Railway /tmp vidē
# Ar drošu JSON parseri (bez eval)
# ===============================================

import os
import json
import zipfile
import tempfile
from typing import List
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from pdfminer.high_level import extract_text
import mammoth
from fpdf import FPDF
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="12.1",
    description="Stable PDF generator + AI comparison"
)

# ===============================================
# HELPERS
# ===============================================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip()


def safe_json_parse(raw: str) -> dict:
    """
    Removes markdown, code fences and tries json.loads safely.
    """
    try:
        cleaned = raw.strip()

        # Remove ```json and ```
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json", "", 1)

        # Remove accidental '`'
        cleaned = cleaned.replace("```", "").strip()

        # Attempt strict JSON load
        return json.loads(cleaned)

    except Exception:
        # Return as text object in PDF
        return {"raw_text": raw}


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


# ===============================================
# AI CALLS
# ===============================================

def parse_requirements_ai(text: str) -> dict:
    prompt = f"""
Izvelc prasības un atgriez JSON formātā:
{{
 "prasības": [...],
 "kopsavilkums": "...",
 "riski": [...],
 "svarīgākie_punkti": [...]
}}
Teksts:
{text}
"""
    res = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return safe_json_parse(res.output_text)


def compare_candidate_ai(req_struct: dict, candidate_text: str) -> dict:
    prompt = f"""
Salīdzini kandidātu ar prasībām. Atgriez JSON formātā:
{{
 "status": "zaļš | dzeltens | sarkans",
 "score": 0-100,
 "atbilst": [...],
 "neatbilst": [...],
 "vajag_pārbaudīt": [...],
 "kopsavilkums": "..."
}}
PRASĪBAS:
{json.dumps(req_struct)}
KANDIDĀTS:
{candidate_text}
"""
    res = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return safe_json_parse(res.output_text)


# ===============================================
# PDF GENERATOR — RAILWAY SAFE
# ===============================================

def generate_pdf(result: dict) -> str:
    tmp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", dir="/tmp")
    tmp_path = tmp_pdf.name
    tmp_pdf.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)

    pdf.cell(0, 10, "Vērtējums", ln=True)
    pdf.set_font("Helvetica", size=10)

    pdf.ln(5)
    pdf.multi_cell(0, 6, json.dumps(result, ensure_ascii=False, indent=2))

    pdf.output(tmp_path)
    return tmp_path


# ===============================================
# MAIN ENDPOINT
# ===============================================

@app.post("/compare_files_with_pdf")
async def compare_files_with_pdf(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # --- Extract requirement text ---
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

        os.unlink(p)

    if not req_text.strip():
        raise HTTPException(400, "Nevar nolasīt prasību dokumentus.")

    req_struct = parse_requirements_ai(req_text)

    # --- Process candidates ---
    all_results = []

    for f in candidates:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name

        cand_text = extract_zip(p)
        os.unlink(p)

        if not cand_text.strip():
            all_results.append({
                "name": f.filename,
                "status": "sarkans",
                "kopsavilkums": "Tukšs fails"
            })
            continue

        ai_eval = compare_candidate_ai(req_struct, cand_text)
        ai_eval["name"] = f.filename
        all_results.append(ai_eval)

    # --- Combine result ---
    final_result = {
        "prasības": req_struct,
        "kandidāti": all_results
    }

    # --- Create PDF ---
    pdf_path = generate_pdf(final_result)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="vertējums.pdf"
    )
