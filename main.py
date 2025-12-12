import os
import zipfile
import tempfile
import shutil
from typing import List, Dict

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

import PyPDF2
import docx
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – Variant A")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===============================
#  FAILU NOLASĪŠANAS FUNKCIJAS
# ===============================

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

    if ext.endswith(".txt") or ext.endswith(".md") or ext.endswith(".rtf"):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except:
            return ""

    # Ignorē Word .doc, Excel .xlsx, CSV u.c. nesteidzoties
    return ""


def read_candidate_folder_recursive(folder_path: str) -> str:
    full_text = ""

    for root, dirs, files in os.walk(folder_path):
        for f in files:
            file_path = os.path.join(root, f)
            full_text += f"\n\n===== FILE: {f} =====\n\n"
            full_text += extract_any_file_text(file_path)

    return full_text


# ===============================
#   AI ANALĪZE
# ===============================

def ai_compare(requirements_text: str, candidate_text: str) -> str:
    prompt = f"""
You are a senior procurement evaluator.

Compare candidate documents with REQUIREMENTS.

Provide:
1. Score (0–100)
2. Strengths
3. Weaknesses
4. Risk level
5. Final verdict (PASS/FAIL)

REQUIREMENTS:
{requirements_text}

CANDIDATE:
{candidate_text}

Return only clean formatted text.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    return response.choices[0].message["content"]


# ===============================
#       API ENDPOINT
# ===============================

@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    requirements: UploadFile = File(...),
    zip_candidates: UploadFile = File(...)
):
    temp_dir = tempfile.mkdtemp()

    # ------------------------------
    # 1) LASĀM PRASĪBU DOKUMENTU
    # ------------------------------
    req_path = os.path.join(temp_dir, requirements.filename)
    with open(req_path, "wb") as f:
        f.write(await requirements.read())

    requirements_text = extract_any_file_text(req_path)

    # ------------------------------
    # 2) IZPAKOJAM KANDIDĀTU ZIP
    # ------------------------------
    zip_path = os.path.join(temp_dir, zip_candidates.filename)
    with open(zip_path, "wb") as f:
        f.write(await zip_candidates.read())

    extract_path = os.path.join(temp_dir, "unzipped")
    os.makedirs(extract_path, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_path)

    # ------------------------------
    # 3) APSTRĀDĀM KANDIDĀTUS (REKURSIJA)
    # ------------------------------
    results = []

    for folder in os.listdir(extract_path):
        folder_path = os.path.join(extract_path, folder)
        if not os.path.isdir(folder_path):
            continue

        candidate_text = read_candidate_folder_recursive(folder_path)
        ai_result = ai_compare(requirements_text, candidate_text)

        results.append({
            "name": folder,
            "analysis": ai_result
        })

    # ------------------------------
    # 4) HTML TABULA
    # ------------------------------

    html = """
    <html>
    <head>
        <title>AI Tender Analyzer</title>
        <style>
            body { font-family: Arial; padding: 20px; }
            table { width: 100%; border-collapse: collapse; }
            td, th { border: 1px solid #ccc; padding: 10px; vertical-align: top; }
            th { background: #eee; }
            .name { font-weight: bold; font-size: 18px; }
        </style>
    </head>
    <body>
    <h2>Tender Analysis Result</h2>
    <table>
        <tr><th>Candidate</th><th>AI Evaluation</th></tr>
    """

    for r in results:
        html += f"""
        <tr>
            <td class="name">{r['name']}</td>
            <td><pre>{r['analysis']}</pre></td>
        </tr>
        """

    html += "</table></body></html>"

    shutil.rmtree(temp_dir)
    return HTMLResponse(content=html)


# ===============================
#   ROOT ENDPOINT
# ===============================

@app.get("/")
def home():
    return {"status": "AI Tender Analyzer Running"}
