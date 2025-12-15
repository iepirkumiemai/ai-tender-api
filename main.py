import os
import tempfile
import zipfile
import datetime
import base64
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from openai import OpenAI
from docx import Document

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – Stable Universal Version")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =======================
# HELPERS
# =======================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip() if text else ""


def extract_docx(path: str) -> str:
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except:
        return ""


def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.lower().endswith((".xml", ".txt")):
                    try:
                        text += clean(z.read(name).decode(errors="ignore"))
                    except:
                        pass
    except:
        pass
    return text


def extract_zip(path: str) -> dict:
    """
    STABILA funkcija:
    - NEKĀDA OpenAI
    - atgriež file_name → bytes
    """
    results = {}

    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            try:
                results[name] = z.read(name)
            except:
                results[name] = b""

    return results


def ai_extract_text_from_binary(filename: str, data: bytes) -> str:
    """
    UNIVERSĀLA AI ekstrakcija:
    PDF, skenēti dokumenti, jebkāds binārs
    """
    b64 = base64.b64encode(data).decode()

    prompt = f"""
You are an expert document analyzer.

The following file is uploaded as BASE64.
Filename: {filename}

TASK:
- Extract ALL readable text
- Preserve structure if possible
- Ignore signatures, noise if unreadable

BASE64 FILE:
{b64}
"""

    r = client.responses.create(
        model="gpt-4o",
        input=prompt
    )

    return r.output_text or ""


# =======================
# GPT LOGIC
# =======================

def ai_extract_requirements(text: str) -> str:
    prompt = f"""
Izvelc VISAS prasības no dokumenta, saglabājot struktūru.

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


def ai_compare(req_json: str, cand_text: str) -> str:
    prompt = f"""
Salīdzini katru prasību ar kandidāta dokumentu saturu.

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

Kandidāta dokumenti:
{cand_text}
"""
    r = client.responses.create(model="gpt-4o", input=prompt)
    return r.output_text


# =======================
# HTML
# =======================

def build_html(requirements: str, comparisons: str) -> str:
    return f"""
<html>
<head>
<meta charset="UTF-8">
<style>
body {{ font-family: Arial; padding: 20px; }}
pre {{ white-space: pre-wrap; }}
</style>
</head>
<body>

<h1>Tendera analīzes atskaite</h1>

<h2>Prasības</h2>
<pre>{requirements}</pre>

<h2>Kandidātu salīdzinājums</h2>
<pre>{comparisons}</pre>

</body>
</html>
"""


# =======================
# API
# =======================

@app.post("/analyze")
async def analyze(
    requirements: list[UploadFile] = File(...),
    candidates: list[UploadFile] = File(...)
):
    req_text = ""

    # -------- REQUIREMENTS --------
    for f in requirements:
        data = await f.read()
        name = f.filename.lower()

        if name.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(data)
                req_text += extract_docx(tmp.name)
                os.unlink(tmp.name)

        elif name.endswith(".edoc"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(data)
                req_text += extract_edoc(tmp.name)
                os.unlink(tmp.name)

        elif name.endswith(".zip"):
            extracted = extract_zip_from_bytes(data := data)
            for fn, b in extracted.items():
                req_text += ai_extract_text_from_binary(fn, b)

        else:
            req_text += ai_extract_text_from_binary(f.filename, data)

    if not req_text.strip():
        raise HTTPException(400, "Neizdevās nolasīt prasību dokumentus.")

    req_structured = ai_extract_requirements(req_text)

    # -------- CANDIDATES --------
    final_comp = ""

    for f in candidates:
        data = await f.read()
        name = f.filename.lower()

        cand_text = ""

        if name.endswith(".zip"):
            extracted = extract_zip_from_bytes(data)
            for fn, b in extracted.items():
                cand_text += ai_extract_text_from_binary(fn, b)
        else:
            cand_text += ai_extract_text_from_binary(f.filename, data)

        comp = ai_compare(req_structured, cand_text)
        final_comp += f"\n\n=== {f.filename} ===\n{comp}"

    # -------- OUTPUT --------
    t = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/report_{t}.html"

    html = build_html(req_structured, final_comp)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return {"status": "ok", "url": f"/download/{Path(path).name}"}


def extract_zip_from_bytes(data: bytes) -> dict:
    results = {}
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        results = extract_zip(tmp_path)
    finally:
        os.unlink(tmp_path)

    return results


@app.get("/download/{filename}")
async def download(filename: str):
    path = f"/tmp/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Fails nav atrasts.")
    return FileResponse(path, media_type="text/html")
