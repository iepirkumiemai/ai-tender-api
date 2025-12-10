import os
import json
import tempfile
import zipfile
from typing import Dict

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI

# OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI-Tender-API", version="4.0")


# ============================================================
# 1. EDOC extraction (ZIP + documents + XML)
# ============================================================
def extract_edoc(path: str) -> Dict:
    results = {
        "documents": [],
        "xml": [],
        "raw_files": []
    }

    with zipfile.ZipFile(path, 'r') as z:
        with tempfile.TemporaryDirectory() as tmpdir:
            z.extractall(tmpdir)

            for root, dirs, files in os.walk(tmpdir):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    ext = filename.lower().split(".")[-1]

                    # XML
                    if ext == "xml":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                        except:
                            content = ""
                        results["xml"].append({"filename": filename, "content": content})
                        continue

                    # TXT
                    if ext == "txt":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    # DOCX
                    if ext == "docx":
                        try:
                            with open(full_path, "rb") as f:
                                extracted = mammoth.convert_to_markdown(f).value
                        except:
                            extracted = ""
                        results["documents"].append({"filename": filename, "text": extracted})
                        continue

                    # PDF
                    if ext == "pdf":
                        try:
                            text = extract_text(full_path)
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    # Everything else
                    results["raw_files"].append({
                        "filename": filename,
                        "path": full_path
                    })

    return results


# ============================================================
# 2. ZIP extraction (PDF / DOCX / TXT)
# ============================================================
def extract_zip(path: str) -> Dict:
    results = {
        "documents": [],
        "raw_files": []
    }

    with zipfile.ZipFile(path, 'r') as z:
        with tempfile.TemporaryDirectory() as tmpdir:
            z.extractall(tmpdir)

            for root, dirs, files in os.walk(tmpdir):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    ext = filename.lower().split(".")[-1]

                    # TXT
                    if ext == "txt":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    # DOCX
                    if ext == "docx":
                        try:
                            with open(full_path, "rb") as f:
                                extracted = mammoth.convert_to_markdown(f).value
                        except:
                            extracted = ""
                        results["documents"].append({"filename": filename, "text": extracted})
                        continue

                    # PDF
                    if ext == "pdf":
                        try:
                            text = extract_text(full_path)
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    # Unknown
                    results["raw_files"].append({
                        "filename": filename,
                        "path": full_path
                    })

    return results


# ============================================================
# 3. AI ANALYSIS (Stable OpenAI ChatCompletion format)
# ============================================================
async def run_ai_analysis(text: str):
    if not text or text.strip() == "":
        text = "(no readable content)"

    prompt = f"""
You are an AI Tender Evaluation Expert.

DOCUMENT CONTENT:
{text}

TASK:
1. Provide a concise summary.
2. Evaluate compliance level (0–100%).
3. Identify non-compliant or missing elements.
4. Provide practical improvement recommendations.

Return STRICT JSON:
- summary
- compliance_score
- non_compliance_items
- recommendations
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    ai_raw = response.choices[0].message.content

    clean = ai_raw.strip().replace("```json", "").replace("```", "").strip()

    return clean


# ============================================================
# 4. PDF extraction
# ============================================================
def extract_pdf(path: str) -> str:
    try:
        return extract_text(path)
    except:
        return ""


# ============================================================
# 5. DOCX extraction
# ============================================================
def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return mammoth.convert_to_markdown(f).value
    except:
        return ""


# ============================================================
# 6. Universal file processor
# ============================================================
def process_file(file_path: str, ext: str) -> Dict:
    ext = ext.lower()

    if ext == "pdf":
        return {"type": "pdf", "text": extract_pdf(file_path)}

    if ext == "docx":
        return {"type": "docx", "text": extract_docx(file_path)}

    if ext == "txt":
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return {"type": "txt", "text": f.read()}
        except:
            return {"type": "txt", "text": ""}

    if ext == "edoc":
        return extract_edoc(file_path)

    if ext == "zip":
        return extract_zip(file_path)

    return {"type": "unknown", "text": ""}


# ============================================================
# 7. Health check
# ============================================================
@app.get("/api/status")
async def status():
    return {"status": "OK", "service": "ai-tender-api"}


# ============================================================
# 8. AUTO-ANALYZE UPLOAD (file → extract → AI)
# ============================================================
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename
    ext = filename.split(".")[-1].lower()

    # Save temp file
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # Extraction
    extraction = process_file(tmp_path, ext)

    # Determine text for AI
    if ext in ["pdf", "docx", "txt"]:
        text = extraction.get("text", "")

    elif ext in ["edoc", "zip"]:
        all_docs = extraction.get("documents", [])
        text = "\n\n".join([d.get("text", "") for d in all_docs])

    else:
        text = ""

    # AI analysis
    ai_raw_json = await run_ai_analysis(text)

    try:
        ai_data = json.loads(ai_raw_json)
    except:
        ai_data = {"error": "AI returned non-JSON", "raw_output": ai_raw_json}

    return JSONResponse({
        "status": "OK",
        "filename": filename,
        "file_type": ext,
        "extracted_text": text,
        "ai_analysis": ai_data,
        "documents": extraction.get("documents"),
        "xml": extraction.get("xml") if ext == "edoc" else None,
        "raw_files": extraction.get("raw_files")
    })
