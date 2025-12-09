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

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI-Tender-API", version="2.1")


# ============================================================
# 1. EDOC → ZIP → Extract PDF/DOCX/TXT + XML
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

                    # XML failu ekstrakcija
                    if ext == "xml":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                        except:
                            content = ""

                        results["xml"].append({
                            "filename": filename,
                            "content": content
                        })
                        continue

                    # TXT
                    if ext == "txt":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except:
                            text = ""

                        results["documents"].append({
                            "filename": filename,
                            "text": text
                        })
                        continue

                    # DOCX
                    if ext == "docx":
                        try:
                            with open(full_path, "rb") as f:
                                extracted = mammoth.convert_to_markdown(f).value
                        except:
                            extracted = ""

                        results["documents"].append({
                            "filename": filename,
                            "text": extracted
                        })
                        continue

                    # PDF
                    if ext == "pdf":
                        try:
                            text = extract_text(full_path)
                        except:
                            text = ""

                        results["documents"].append({
                            "filename": filename,
                            "text": text
                        })
                        continue

                    # Citi faili – saglabājam info
                    results["raw_files"].append({
                        "filename": filename,
                        "path": full_path
                    })

    return results


# ============================================================
# 2. AI ANALĪZE (Stabilā OpenAI metode)
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

Respond strictly in JSON with keys:
- summary
- compliance_score
- non_compliance_items
- recommendations
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message["content"]


# ============================================================
# 3. PDF ekstrakcija
# ============================================================
def extract_pdf(path: str) -> str:
    try:
        return extract_text(path)
    except:
        return ""


# ============================================================
# 4. DOCX ekstrakcija
# ============================================================
def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return mammoth.convert_to_markdown(f).value
    except:
        return ""


# ============================================================
# 5. Universālā faila apstrāde
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

    return {"type": "unknown", "text": ""}


# ============================================================
# 6. HEALTH CHECK
# ============================================================
@app.get("/api/status")
async def status():
    return {"status": "OK", "service": "ai-tender-api"}


# ============================================================
# 7. AUTO-ANALYZE UPLOAD: ekstrakcija + AI analīze
# ============================================================
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename
    ext = filename.split(".")[-1].lower()

    # Saglabā failu pagaidu vietā
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # Ekstrakcija
    extraction = process_file(tmp_path, ext)

    # Izvēlamies tekstu analīzei
    if ext in ["pdf", "docx", "txt"]:
        text = extraction.get("text", "")

    elif ext == "edoc":
        all_docs = extraction.get("documents", [])
        text = "\n\n".join([d.get("text", "") for d in all_docs])

    else:
        text = ""

    # AI analīze
    ai_json_text = await run_ai_analysis(text)

    try:
        ai_data = json.loads(ai_json_text)
    except:
        ai_data = {"error": "AI returned non-JSON", "raw": ai_json_text}

    # Atbilde
    return JSONResponse({
        "status": "OK",
        "filename": filename,
        "file_type": ext,
        "extracted_text": text,
        "ai_analysis": ai_data,
        "edoc_xml": extraction.get("xml") if ext == "edoc" else None,
        "edoc_raw_files": extraction.get("raw_files") if ext == "edoc" else None
    })
