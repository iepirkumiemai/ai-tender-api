import os
import zipfile
import tempfile
import shutil
from typing import List
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

import PyPDF2
import docx
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – Variant A Chunk Safe")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================================
# FILE READERS
# ======================================================

def extract_text_from_pdf(path: str) -> str:
    try:
        reader = PyPDF2.PdfReader(path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except:
        return ""

def extract_text_from_docx(path: str) -> str:
    try:
        doc = docx.Document(path)
        return "\n".join([p.text for p in doc.paragraphs])
    except:
        return ""

def extract_any_file_text(path: str) -> str:
    ext = path.lower()
    if ext.endswith(".pdf"):
        return extract_text_from_pdf(path)
    if ext.endswith(".docx"):
        return extract_text_from_docx(path)
    if ext.endswith(".txt") or ext.endswith(".rtf") or ext.endswith(".md"):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except:
            return ""
    return ""

def read_candidate_folder_recursive(folder_path: str) -> str:
    text = ""
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            file_path = os.path.join(root, f)
            text += f"\n===== FILE: {f} =====\n"
            text += extract_any_file_text(file_path)
    return text

# ======================================================
# SAFE CHUNKING LOGIC (token limit fix)
# ======================================================

def chunk_text(text: str, max_chars: int = 10000) -> List[str]:
    chunks = []
    while len(text) > max_chars:
        part = text[:max_chars]
        chunks.append(part)
        text = text[max_chars:]
    chunks.append(text)
    return chunks

# ======================================================
# GPT-4o ANALYSIS (SAFE FOR LARGE INPUTS)
# ======================================================

def ai_compare(requirements_text: str, candidate_text: str) -> str:
    chunks = chunk_text(candidate_text, max_chars=8000)  # safe for GPT-4o
    partial_results = []

    for i, chunk in enumerate(chunks):
        prompt = f"""
You are a senior procurement evaluator.

Evaluate this PART of a candidate submission against REQUIREMENTS.

PART {i+1} of {len(chunks)}:

CANDIDATE SECTION:
{chunk}

REQUIREMENTS:
{requirements_text}

Return:
1. Findings summary
2. Potential risks
3. Compliance notes
Only the text, no formatting.
"""

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )

        partial_results.append(response.choices[0].message["content"])

    # Now combine partial results
    final_prompt = f"""
Combine the following partial evaluation notes into one final professional tender evaluation.

NOTES:
{partial_results}

Return:

1. Score (0–100)
2. Strengths
3. Weaknesses
4. Risk level
5. Final PASS/FAIL
"""

    summary = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": final_prompt}],
        temperature=0.2,
    )

    return summary.choices[0].message["content"]

# ======================================================
# API ENDPOINT
# ======================================================

@app.post("/analyze", response_class=HTMLResponse)
async def analyze(requirements: UploadFile = File(...),
                  zip_candidates: UploadFile = File(...)):

    temp_dir = tempfile.mkdtemp()

    # 1. Save requirements
    req_path = os.path.join(temp_dir, requirements.filename)
    with open(req_path, "wb") as f:
        f.write(await requirements.read())

    requirements_text = extract_any_file_text(req_path)

    # 2. Extract ZIP
    zip_path = os.path.join(temp_dir, zip_candidates.filename)
    with open(zip_path, "wb") as f:
        f.write(await zip_candidates.read())

    extract_path = os.path.join(temp_dir, "unzipped")
    os.makedirs(extract_path, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_path)

    results = []

    for folder in os.listdir(extract_path):
        folder_path = os.path.join(extract_path, folder)
        if not os.path.isdir(folder_path):
            continue

        candidate_text = read_candidate_folder_recursive(folder_path)
        ai_result = ai_compare(requirements_text, candidate_text)

        results.append({"name": folder, "analysis": ai_result})

    # HTML output
    html = """
    <html><head>
    <style>
    body { font-family: Arial; padding: 20px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px; border: 1px solid #ccc; }
    th { background: #eee; }
    </style>
    </head><body>
    <h2>Tender Analysis Result</h2>
    <table><tr><th>Candidate</th><th>Evaluation</th></tr>
    """

    for r in results:
        html += f"<tr><td>{r['name']}</td><td><pre>{r['analysis']}</pre></td></tr>"

    html += "</table></body></html>"

    shutil.rmtree(temp_dir)
    return HTMLResponse(content=html)

@app.get("/")
def home():
    return {"status": "running"}
