# ============================================================
# main.py — AI Tender Analyzer (Separate File Analysis Mode)
# ============================================================

import os
import zipfile
import tempfile
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="Tender Analyzer", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================
# Extract TEXT from supported file types
# ============================================================

def extract_text_from_file(path: str, name: str) -> str:
    name = name.lower()

    # PDF — minimalistic extractor (OpenAI handles missing bits)
    if name.endswith(".pdf"):
        try:
            from pdfminer.high_level import extract_text
            return extract_text(path)
        except:
            return ""

    # DOCX
    if name.endswith(".docx"):
        try:
            import mammoth
            with open(path, "rb") as f:
                result = mammoth.extract_raw_text(f)
                return result.value
        except:
            return ""

    # EDOC (XML container)
    if name.endswith(".edoc") or name.endswith(".xml"):
        try:
            text = ""
            with zipfile.ZipFile(path, "r") as z:
                for entry in z.namelist():
                    if entry.endswith(".xml") or entry.endswith(".txt"):
                        text += z.read(entry).decode(errors="ignore")
            return text
        except:
            return ""

    # TXT / HTML
    if name.endswith(".txt") or name.endswith(".html"):
        try:
            return open(path, "r", encoding="utf-8", errors="ignore").read()
        except:
            return ""

    return ""


# ============================================================
# Separate extraction for ZIP → returns list of (filename, text)
# ============================================================

def extract_zip_separate(path: str):
    results = []

    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():

            if name.endswith("/"):
                continue

            # Save entry to temp
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(z.read(name))
                p = tmp.name

            text = extract_text_from_file(p, name)

            results.append({"filename": name, "text": text})

            os.unlink(p)

    return results


# ============================================================
# AI — Compare single candidate file with requirements
# ============================================================

def ai_compare_single(requirements: str, candidate_text: str, fname: str) -> str:

    prompt = f"""
You are an expert in EU procurement evaluation.

Compare the following candidate document **separately** with the requirements.

Return STRICT MARKDOWN.

Document Name: {fname}

REQUIREMENTS:
{requirements}

CANDIDATE FILE CONTENT:
{candidate_text}

RETURN FORMAT (MANDATORY):

### File: {fname}

1. **Score (0–100):** ...
2. **Strengths:** list
3. **Weaknesses:** list
4. **Legal/Compliance Risk Level:** LOW | MEDIUM | HIGH
5. **Verdict:** PASS | FAIL
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2500,
        temperature=0
    )

    return response.choices[0].message.content


# ============================================================
# AI — Compress requirements to safe token length
# ============================================================

def ai_compress_requirements(text: str) -> str:

    prompt = f"""
Shorten this requirements document to a compact summary keeping all legal,
financial, and technical criteria necessary for evaluating offers.

Return short text (max 1200 words).
TEXT:
{text}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
        temperature=0
    )

    return response.choices[0].message.content


# ============================================================
# MAIN ENDPOINT /analyze
# ============================================================

@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    requirements_file: UploadFile = File(...),
    candidate_zip: UploadFile = File(...)
):

    # ================= Requirements ==================
    req_tmp = tempfile.NamedTemporaryFile(delete=False)
    req_tmp.write(await requirements_file.read())
    req_tmp.close()

    requirements_text = extract_text_from_file(req_tmp.name, requirements_file.filename)
    os.unlink(req_tmp.name)

    if len(requirements_text) < 50:
        return HTMLResponse("<h2>Requirements file unreadable or empty.</h2>")

    # Compress to avoid token overflow
    compressed_req = ai_compress_requirements(requirements_text)

    # ================= Candidates ZIP ==================
    zip_tmp = tempfile.NamedTemporaryFile(delete=False)
    zip_tmp.write(await candidate_zip.read())
    zip_tmp.close()

    extracted_files = extract_zip_separate(zip_tmp.name)
    os.unlink(zip_tmp.name)

    # ================= AI evaluation ==================
    rows = ""

    for f in extracted_files:
        fname = f["filename"]
        text = f["text"]

        if len(text.strip()) < 20:
            evaluation = "Empty or unreadable file."
        else:
            evaluation = ai_compare_single(compressed_req, text, fname)

        rows += f"<tr><td>{fname}</td><td><pre>{evaluation}</pre></td></tr>"

    # ================= HTML output ==================
    html = f"""
    <html><head>
    <style>
        body {{ font-family: Arial; padding: 20px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; border: 1px solid #ccc; vertical-align: top; }}
        th {{ background: #f0f0f0; }}
        pre {{ white-space: pre-wrap; }}
    </style>
    </head><body>
    <h2>Tender Evaluation Result (Separate File Analysis)</h2>
    <table>
        <tr><th>File</th><th>Evaluation</th></tr>
        {rows}
    </table>
    </body></html>
    """

    return HTMLResponse(html)
