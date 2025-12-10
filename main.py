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

# Init OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI-Tender-API", version="5.0")


# ============================================================
# 1. Split long text into chunks to avoid AI token limits
# ============================================================
def split_text_into_chunks(text: str, max_chars: int = 200000) -> list:
    chunks = []
    length = len(text)

    if length <= max_chars:
        return [text]

    for i in range(0, length, max_chars):
        chunks.append(text[i:i + max_chars])

    return chunks


# ============================================================
# 2. AI single chunk analysis
# ============================================================
async def run_ai_analysis(text: str):
    if not text or text.strip() == "":
        text = "(no readable content)"

    prompt = f"""
You are an AI Tender Evaluation Expert.

DOCUMENT CHUNK:
{text}

TASK:
1. Provide a concise summary of the chunk.
2. Evaluate compliance level (0–100%).
3. Identify non-compliant or missing items.
4. Provide practical recommendations.

Respond with STRICT JSON ONLY:
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
# 3. Analyze long text using chunks
# ============================================================
async def analyze_large_text(text: str):
    chunks = split_text_into_chunks(text)
    results = []

    for idx, chunk in enumerate(chunks):
        raw = await run_ai_analysis(chunk)

        try:
            json_data = json.loads(raw)
        except:
            json_data = {"summary": "", "compliance_score": 0,
                         "non_compliance_items": [], "recommendations": []}

        results.append(json_data)

    # Combine all summaries
    combined_summary = " ".join([r.get("summary", "") for r in results])

    # Average compliance score
    scores = [r.get("compliance_score", 0) for r in results]
    avg_score = sum(scores) / len(scores) if scores else 0

    # Merge non-compliance
    non_comp = []
    for r in results:
        items = r.get("non_compliance_items", [])
        non_comp.extend(items)

    # Merge recommendations
    recs = []
    for r in results:
        recs.extend(r.get("recommendations", []))

    return {
        "summary": combined_summary,
        "compliance_score": avg_score,
        "non_compliance_items": list(set(non_comp)),
        "recommendations": list(set(recs)),
        "chunks_analyzed": len(chunks)
    }


# ============================================================
# 4. Extraction: PDF, DOCX, TXT
# ============================================================
def extract_pdf(path: str) -> str:
    try:
        return extract_text(path)
    except:
        return ""


def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return mammoth.convert_to_markdown(f).value
    except:
        return ""


# ============================================================
# 5. Extract EDOC (ZIP + XML)
# ============================================================
def extract_edoc(path: str) -> Dict:
    results = {"documents": [], "xml": [], "raw_files": []}

    with zipfile.ZipFile(path, 'r') as z:
        with tempfile.TemporaryDirectory() as tmpdir:
            z.extractall(tmpdir)

            for root, dirs, files in os.walk(tmpdir):
                for filename in files:
                    ext = filename.lower().split(".")[-1]
                    full_path = os.path.join(root, filename)

                    if ext == "xml":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                xml = f.read()
                        except:
                            xml = ""
                        results["xml"].append({"filename": filename, "content": xml})
                        continue

                    if ext == "txt":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    if ext == "docx":
                        try:
                            with open(full_path, "rb") as f:
                                text = mammoth.convert_to_markdown(f).value
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    if ext == "pdf":
                        try:
                            text = extract_text(full_path)
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    results["raw_files"].append({"filename": filename, "path": full_path})

    return results


# ============================================================
# 6. Extract ZIP files (PDF / DOCX / TXT)
# ============================================================
def extract_zip(path: str) -> Dict:
    results = {"documents": [], "raw_files": []}

    with zipfile.ZipFile(path, 'r') as z:
        with tempfile.TemporaryDirectory() as tmpdir:
            z.extractall(tmpdir)

            for root, dirs, files in os.walk(tmpdir):
                for filename in files:
                    ext = filename.lower().split(".")[-1]
                    full_path = os.path.join(root, filename)

                    if ext == "txt":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    if ext == "docx":
                        try:
                            with open(full_path, "rb") as f:
                                text = mammoth.convert_to_markdown(f).value
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    if ext == "pdf":
                        try:
                            text = extract_text(full_path)
                        except:
                            text = ""
                        results["documents"].append({"filename": filename, "text": text})
                        continue

                    results["raw_files"].append({"filename": filename, "path": full_path})

    return results


# ============================================================
# 7. Universal file processor
# ============================================================
def process_file(path: str, ext: str) -> Dict:
    ext = ext.lower()

    if ext == "pdf":
        return {"type": "pdf", "text": extract_pdf(path)}

    if ext == "docx":
        return {"type": "docx", "text": extract_docx(path)}

    if ext == "txt":
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return {"type": "txt", "text": f.read()}
        except:
            return {"type": "txt", "text": ""}

    if ext == "edoc":
        return extract_edoc(path)

    if ext == "zip":
        return extract_zip(path)

    return {"type": "unknown", "text": ""}


# ============================================================
# 8. Health check
# ============================================================
@app.get("/api/status")
async def status():
    return {"status": "OK", "service": "ai-tender-api"}


# ============================================================
# 9. Upload endpoint with AUTO-CHUNK ANALYSIS
# ============================================================
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename
    ext = filename.split(".")[-1].lower()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await file.read())
        path = tmp.name

    extraction = process_file(path, ext)

    # Extract text depending on format
    if ext in ["pdf", "docx", "txt"]:
        text = extraction.get("text", "")

    elif ext in ["zip", "edoc"]:
        docs = extraction.get("documents", [])
        text = "\n\n".join([d.get("text", "") for d in docs])

    else:
        text = ""

    # AI chunk-based analysis
    ai_data = await analyze_large_text(text)

    return JSONResponse({
        "status": "OK",
        "filename": filename,
        "file_type": ext,
        "ai_analysis": ai_data,
        "documents": extraction.get("documents"),
        "xml": extraction.get("xml") if ext == "edoc" else None,
        "raw_files": extraction.get("raw_files")
    })
