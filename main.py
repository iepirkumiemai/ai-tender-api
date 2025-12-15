import os
import zipfile
import tempfile
import datetime
from pathlib import Path

import pdfplumber
from docx import Document
from openpyxl import load_workbook
from lxml import etree

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from openai import OpenAI


# ======================
# CONFIG
# ======================

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – C Variant (Stable)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================
# TEXT HELPERS
# ======================

def clean(t: str) -> str:
    return t.replace("\x00", "").strip() if t else ""


# ======================
# FILE EXTRACTORS
# ======================

def extract_docx(path: str) -> str:
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except:
        return ""


def extract_pdf_text(path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except:
        pass
    return clean(text)


def extract_pdf_scan(path: str) -> str:
    with open(path, "rb") as f:
        pdf_bytes = f.read()

    response = client.responses.create(
        model="gpt-4o",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text",
                     "text": "Extract ALL text from this scanned PDF. Preserve structure."},
                    {
                        "type": "input_file",
                        "mime_type": "application/pdf",
                        "data": pdf_bytes
                    }
                ]
            }
        ]
    )

    return response.output_text or ""


def extract_xlsx(path: str) -> str:
    text = ""
    try:
        wb = load_workbook(path, data_only=True)
        for sheet in wb.worksheets:
            text += f"\n[SHEET: {sheet.title}]\n"
            for row in sheet.iter_rows(values_only=True):
                line = " | ".join(str(c) for c in row if c is not None)
                text += line + "\n"
    except:
        pass
    return clean(text)


def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.lower().endswith(".xml"):
                    xml = z.read(name)
                    root = etree.fromstring(xml)
                    text += " ".join(root.itertext())
    except:
        pass
    return clean(text)


# ======================
# ZIP HANDLER (RECURSIVE)
# ======================

def extract_any(path: str) -> str:
    collected = ""

    if path.lower().endswith(".docx"):
        collected += extract_docx(path)

    elif path.lower().endswith(".pdf"):
        text = extract_pdf_text(path)
        if len(text) < 50:
            text = extract_pdf_scan(path)
        collected += text

    elif path.lower().endswith(".xlsx"):
        collected += extract_xlsx(path)

    elif path.lower().endswith(".edoc"):
        collected += extract_edoc(path)

    elif path.lower().endswith(".txt"):
        with open(path, "r", errors="ignore") as f:
            collected += f.read()

    elif path.lower().endswith(".zip"):
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(z.read(name))
                    tmp_path = tmp.name
                collected += extract_any(tmp_path)
                os.unlink(tmp_path)

    return clean(collected)


# ======================
# GPT LOGIC
# ======================

def ai_extract_requirements(text: str) -> str:
    prompt = f"""
Izvelc VISAS prasības no iepirkuma nolikuma.

Formāts:
[
  {{
    "prasība": "...",
    "pamatojums": "..."
  }}
]

Dokuments:
{text}
"""
    r = client.responses.create(model="gpt-4o", input=prompt)
    return r.output_text


def ai_compare(req_json: str, candidate_text: str) -> str:
    prompt = f"""
Salīdzini katru prasību ar kandidāta piedāvājumu.

Statusi:
- Atbilst
- Daļēji atbilst
- Neatbilst

Formāts:
[
  {{
    "prasība": "...",
    "statuss": "...",
    "pamatojums": "..."
  }}
]

Prasības:
{req_json}

Kandidāta piedāvājums:
{candidate_text}
"""
    r = client.responses.create(model="gpt-4o", input=prompt)
    return r.output_text


# ======================
# HTML
# ======================

def build_html(req: str, comp: str) -> str:
    return f"""
<html>
<head><meta charset="UTF-8"></head>
<body>
<h1>Tendera analīzes atskaite</h1>

<h2>Prasības</h2>
<pre>{req}</pre>

<h2>Salīdzinājums</h2>
<pre>{comp}</pre>
</body>
</html>
"""


# ======================
# API
# ======================

@app.post("/analyze")
async def analyze(
    requirements: list[UploadFile] = File(...),
    candidates: list[UploadFile] = File(...)
):
    req_text = ""
    cand_results = ""

    for f in requirements:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            path = tmp.name
        req_text += extract_any(path)
        os.unlink(path)

    if not req_text.strip():
        raise HTTPException(400, "Prasību dokumenti nav nolasīti.")

    req_structured = ai_extract_requirements(req_text)

    for f in candidates:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await f.read())
            path = tmp.name
        cand_text = extract_any(path)
        os.unlink(path)

        if cand_text.strip():
            comp = ai_compare(req_structured, cand_text)
            cand_results += f"\n\n=== {f.filename} ===\n{comp}"
        else:
            cand_results += f"\n\n=== {f.filename} ===\nNav nolasāma teksta."

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = f"/tmp/report_{ts}.html"

    with open(out, "w", encoding="utf-8") as f:
        f.write(build_html(req_structured, cand_results))

    return {"url": f"/download/{Path(out).name}"}


@app.get("/download/{filename}")
async def download(filename: str):
    path = f"/tmp/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Fails nav atrasts")
    return FileResponse(path, media_type="text/html")
