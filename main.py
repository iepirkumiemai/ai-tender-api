# ============================================
# main.py — Tender Document Analyzer v7.0
# ============================================

import os
import zipfile
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from typing import List, Tuple
import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Analyzer",
    version="7.0",
    description="Document analyzer for PDF, DOCX, EDOC and ZIP archives using GPT-4.1"
)

# ============================================
# UTILS — TEXT CLEANING
# ============================================

def clean_text(text: str) -> str:
    return text.replace("\x00", "").strip()


# ============================================
# PDF EXTRACTION
# ============================================

def extract_pdf(path: str) -> str:
    try:
        return clean_text(extract_text(path))
    except:
        return ""


# ============================================
# DOCX EXTRACTION
# ============================================

def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
            return clean_text(result.value)
    except:
        return ""


# ============================================
# EDOC EXTRACTION (simplified — text only)
# ============================================

def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith(".xml") or name.endswith(".txt"):
                    text += clean_text(z.read(name).decode(errors="ignore"))
    except:
        pass
    return text


# ============================================
# ZIP EXTRACTION — FULL RECURSIVE PARSE
# ============================================

def extract_zip(path: str) -> str:
    combined_text = ""

    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():

            if name.endswith("/"):
                continue  # skip folder

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(z.read(name))
                tmp_path = tmp.name

            # Process nested types
            if name.lower().endswith(".pdf"):
                combined_text += extract_pdf(tmp_path)

            elif name.lower().endswith(".docx"):
                combined_text += extract_docx(tmp_path)

            elif name.lower().endswith(".edoc"):
                combined_text += extract_edoc(tmp_path)

            elif name.lower().endswith(".zip"):
                combined_text += extract_zip(tmp_path)

            # Remove temp file
            os.unlink(tmp_path)

    return combined_text


# ============================================
# AI ANALYSIS — GPT-4.1
# ============================================

def analyze_with_gpt(text: str) -> dict:

    prompt = f"""
You are an expert evaluator for tender documents.

Analyze the following document text. Return structured JSON:

{{
    "summary": "...",
    "risk_level": "...",
    "key_requirements": [...],
    "missing_elements": [...],
    "recommendations": [...]
}}

Document text (may be incomplete):
{text}
    """

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


# ============================================
# MAIN ENDPOINT — /analyze
# ============================================

@app.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):

    filename = file.filename.lower()

    # Save uploaded file
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # ---------------------------
    # Detect file type
    # ---------------------------
    if filename.endswith(".pdf"):
        extracted = extract_pdf(tmp_path)

    elif filename.endswith(".docx"):
        extracted = extract_docx(tmp_path)

    elif filename.endswith(".edoc"):
        extracted = extract_edoc(tmp_path)

    elif filename.endswith(".zip"):
        extracted = extract_zip(tmp_path)

    else:
        os.unlink(tmp_path)
        raise HTTPException(400, f"Unsupported file type: {filename}")

    os.unlink(tmp_path)

    if not extracted.strip():
        return JSONResponse({
            "status": "error",
            "reason": "No readable text extracted from document."
        })

    # ---------------------------
    # AI analysis
    # ---------------------------
    ai_result = analyze_with_gpt(extracted)

    return {
        "status": "OK",
        "filename": file.filename,
        "file_type": filename.split(".")[-1],
        "extracted_text_preview": extracted[:2500],  # safety
        "ai_analysis": ai_result
    }
