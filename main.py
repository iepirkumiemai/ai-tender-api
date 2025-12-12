import os
import json
import tempfile
import zipfile
from typing import List, Dict

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse

from PyPDF2 import PdfReader
from docx import Document
from openai import OpenAI


app = FastAPI(title="AI Iepirkumi – Document Analyzer", version="2.0")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ============================================================
# FAILU NOLASĪŠANA
# ============================================================

def read_pdf(file_path: str) -> str:
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception:
        return ""


def read_docx(file_path: str) -> str:
    try:
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception:
        return ""


def read_txt(file_path: str) -> str:
    try:
        return open(file_path, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""


def read_zip(file_path: str) -> str:
    text = ""
    with zipfile.ZipFile(file_path, "r") as z:
        for name in z.namelist():
            with z.open(name) as f:
                try:
                    content = f.read().decode("utf-8", errors="ignore")
                    text += "\n\n===== FILE: " + name + " =====\n\n"
                    text += content
                except Exception:
                    pass
    return text


def load_document(file: UploadFile) -> str:
    suffix = file.filename.lower()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    if suffix.endswith(".pdf"):
        return read_pdf(tmp_path)

    if suffix.endswith(".docx"):
        return read_docx(tmp_path)

    if suffix.endswith(".txt"):
        return read_txt(tmp_path)

    if suffix.endswith(".zip") or suffix.endswith(".edoc"):
        return read_zip(tmp_path)

    return ""


# ============================================================
# BLOKU SADALĪŠANA — 20 000 rakstzīmes
# ============================================================

def split_into_blocks(text: str, block_size: int = 20000) -> List[str]:
    return [text[i:i + block_size] for i in range(0, len(text), block_size)]


# ============================================================
# GPT ANALĪZE
# ============================================================

def analyze_block(block_text: str, block_number: int) -> Dict:
    prompt = f"""
You are an AI tender analysis engine.

Analyze the following document block #{block_number}.
Extract:
- Requirements
- Criteria
- Constraints
- Expected deliverables
- Anything relevant as input for procurement evaluation.

Return structured JSON.

BLOCK CONTENT:
{block_text}
"""

    response = client.responses.create(
        model="gpt-4o",
        input=prompt,
    )

    try:
        data = json.loads(response.output[0].content[0].text)
        return data
    except Exception:
        return {"block": block_number, "raw_text": response.output[0].content[0].text}


# ============================================================
# HTML IZVEIDE
# ============================================================

def generate_html(results_json: Dict) -> str:
    html = """
<html>
<head>
<style>
body { font-family: Arial; padding: 20px; }
pre { background: #f0f0f0; padding: 15px; border-radius: 5px; white-space: pre-wrap; }
</style>
</head>
<body>
<h1>AI Analysis Report</h1>
<pre>
"""
    html += json.dumps(results_json, indent=4, ensure_ascii=False)
    html += "</pre></body></html>"
    return html


# ============================================================
# API ENDPOINTS
# ============================================================

@app.post("/analyze", response_class=HTMLResponse)
async def analyze(requirements: UploadFile = File(...)):
    # 1. Load document
    text = load_document(requirements)

    if not text.strip():
        return HTMLResponse("<h1>Error: Empty or unreadable document</h1>", status_code=400)

    # 2. Split into 20k blocks
    blocks = split_into_blocks(text)

    results = {"blocks": []}

    # 3. GPT analysis per block
    for i, block in enumerate(blocks, start=1):
        block_result = analyze_block(block, i)
        results["blocks"].append(block_result)

    # 4. Generate final HTML
    html = generate_html(results)

    return HTMLResponse(content=html, media_type="text/html")


@app.get("/")
def root():
    return {"message": "AI Iepirkumi API is running."}
