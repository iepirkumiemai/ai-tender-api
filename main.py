# ============================================================
# main.py — AI Tender Engine (Stable HTML Download Version)
# ============================================================

import os
import zipfile
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, Response
from typing import List
from openai import OpenAI
from pdfminer.high_level import extract_text

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Engine",
    version="1.0",
    description="Stable version with HTML downloadable output."
)


# ============================================================
#  TEXT CLEANER
# ============================================================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip()


# ============================================================
#  FILE EXTRACTORS (PDF, DOCX, EDOC, ZIP)
# ============================================================

def extract_pdf(path: str) -> str:
    try:
        return clean(extract_text(path))
    except:
        return ""


def extract_docx(path: str) -> str:
    # DOCX is a ZIP → minimal extractor
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith(".xml"):
                    try:
                        xml = z.read(name).decode("utf-8", errors="ignore")
                        text += clean(xml)
                    except:
                        continue
    except:
        pass
    return text


def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for n in z.namelist():
                if n.endswith(".xml") or n.endswith(".txt"):
                    try:
                        text += clean(z.read(n).decode("utf-8", errors="ignore"))
                    except:
                        continue
    except:
        pass
    return text


def extract_zip(path: str) -> str:
    result = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for n in z.namelist():
                if n.endswith("/"):
                    continue
                data = z.read(n)
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(data)
                    p = tmp.name
                n_low = n.lower()

                if n_low.endswith(".pdf"):
                    result += extract_pdf(p)
                elif n_low.endswith(".docx"):
                    result += extract_docx(p)
                elif n_low.endswith(".edoc"):
                    result += extract_edoc(p)
                elif n_low.endswith(".zip"):
                    result += extract_zip(p)

                os.unlink(p)
    except:
        pass
    return clean(result)


# ============================================================
#  AI FUNCTIONS
# ============================================================

def ai_requirements(text: str) -> str:
    prompt = f"""
You are an AI that extracts tender requirements.

Return a short structured summary:

- Key requirements list
- Mandatory conditions
- Evaluation criteria

Respond strictly in HTML <div> elements.
Here is the document text:
{text}
"""
    r = client.responses.create(
        model="gpt-4o",
        input=prompt
    )
    return r.output_text


def ai_candidate(req_html: str, candidate_text: str) -> str:
    prompt = f"""
You are comparing a candidate ZIP with tender requirements.

Requirements (HTML):
{req_html}

Candidate text:
{candidate_text}

Return STRICT HTML with:

<h2>Match Score (0-100)</h2>
<h2>Status: GREEN / YELLOW / RED</h2>
<h2>Matched Requirements</h2>
<ul>...</ul>
<h2>Missing Requirements</h2>
<ul>...</ul>
<h2>Risks</h2>
<ul>...</ul>
<h2>Summary</h2>
<p>...</p>
"""
    r = client.responses.create(
        model="gpt-4o",
        input=prompt
    )
    return r.output_text


# ============================================================
#  MAIN ENDPOINT — RETURNS DOWNLOADABLE HTML
# ============================================================

@app.post("/compare_files")
async def compare_files(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):

    # ---- Extract requirements ----
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
        else:
            raise HTTPException(400, f"Unsupported requirement file: {name}")

        os.unlink(p)

    if not req_text.strip():
        raise HTTPException(400, "No readable text in requirements.")

    # ---- AI: Requirements HTML block ----
    req_html = ai_requirements(req_text)

    # ---- AI: Candidates ----
    final_html = """
<html>
<head>
<title>Tender Analysis</title>
<style>
body { font-family: Arial; padding: 20px; }
.green { color: green; font-weight: bold; }
.yellow { color: orange; font-weight: bold; }
.red { color: red; font-weight: bold; }
.block { border:1px solid #ddd; padding:15px; margin-bottom:20px; }
</style>
</head>
<body>
<h1>Tender Comparison Report</h1>
<h2>Requirements Summary</h2>
<div class="block">
""" + req_html + "</div>"

    # ---- Process each candidate ----
    for f in candidates:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            p = tmp.name
        name = f.filename.lower()

        if not name.endswith(".zip"):
            raise HTTPException(400, f"Candidate must be ZIP: {name}")

        cand_text = extract_zip(p)
        os.unlink(p)

        if not cand_text.strip():
            cand_html = "<p class='red'>UNREADABLE ZIP</p>"
        else:
            cand_html = ai_candidate(req_html, cand_text)

        final_html += f"""
        <h2>Candidate: {f.filename}</h2>
        <div class="block">{cand_html}</div>
        """

    final_html += "</body></html>"

    # ---- Return as downloadable HTML file ----
    return Response(
        content=final_html,
        media_type="text/html",
        headers={
            "Content-Disposition": "attachment; filename=analysis.html"
        }
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    return {"status": "ok"}
