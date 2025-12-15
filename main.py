import os
import zipfile
import tempfile
import datetime
from pathlib import Path
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from docx import Document
from openai import OpenAI


# =======================
# CONFIG
# =======================

MAX_FILE_SIZE_MB = 50
MAX_ZIP_FILES = 200
VISION_MODEL = "gpt-4o"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – C Variant (Production)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =======================
# HELPERS
# =======================

def check_size(f: UploadFile):
    if f.size and f.size > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"Fails {f.filename} ir par lielu.")


def extract_docx_text(path: str) -> str:
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""


def vision_extract_pdf(path: str) -> str:
    try:
        with open(path, "rb") as f:
            response = client.responses.create(
                model=VISION_MODEL,
                input=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Extract ALL readable text from this PDF document. "
                                "Preserve structure, lists and tables. "
                                "Do NOT summarize or omit anything."
                            )
                        },
                        {
                            "type": "input_file",
                            "mime_type": "application/pdf",
                            "data": f.read()
                        }
                    ]
                }],
                max_output_tokens=4096
            )
        return response.output_text or ""
    except Exception:
        return ""


def extract_zip_files(path: str) -> List[str]:
    extracted = []

    with zipfile.ZipFile(path, "r") as z:
        names = [n for n in z.namelist() if not n.endswith("/")][:MAX_ZIP_FILES]

        for name in names:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.write(z.read(name))
            tmp.close()
            extracted.append(tmp.name)

    return extracted


def classify_candidate_files(paths: List[str]) -> dict:
    result = {
        "text_files": [],
        "excel_files": [],
        "signature_files": [],
    }

    for p in paths:
        l = p.lower()
        if l.endswith((".pdf", ".doc", ".docx")):
            result["text_files"].append(p)
        elif l.endswith((".xls", ".xlsx", ".csv")):
            result["excel_files"].append(p)
        elif l.endswith((".edoc", ".asice", ".p7s")):
            result["signature_files"].append(p)

    return result


# =======================
# GPT LOGIC
# =======================

def ai_extract_requirements(text: str) -> str:
    prompt = f"""
Izvelc VISAS prasības no dokumenta.

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
    return r.output_text or ""


def ai_compare(req_json: str, cand_text: str) -> str:
    prompt = f"""
Salīdzini katru prasību ar kandidāta piedāvājumu.

Statusi:
- Atbilst
- Daļēji atbilst
- Neatbilst
- Nav iesniegts

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
{cand_text}
"""
    r = client.responses.create(model="gpt-4o", input=prompt)
    return r.output_text or ""


# =======================
# HTML
# =======================

def build_html(req: str, comp: str) -> str:
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
<pre>{req}</pre>

<h2>Kandidātu salīdzinājums</h2>
<pre>{comp}</pre>
</body>
</html>
"""


# =======================
# API
# =======================

@app.post("/analyze")
async def analyze(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):
    req_text = ""

    # -------- REQUIREMENTS --------
    for f in requirements:
        check_size(f)
        data = await f.read()

        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(data)
        tmp.close()

        try:
            n = f.filename.lower()
            if n.endswith(".pdf"):
                req_text += vision_extract_pdf(tmp.name)
            elif n.endswith((".doc", ".docx")):
                req_text += extract_docx_text(tmp.name)
            elif n.endswith(".zip"):
                for p in extract_zip_files(tmp.name):
                    if p.lower().endswith(".pdf"):
                        req_text += vision_extract_pdf(p)
                    elif p.lower().endswith((".doc", ".docx")):
                        req_text += extract_docx_text(p)
                    os.unlink(p)
        finally:
            os.unlink(tmp.name)

    if not req_text.strip():
        raise HTTPException(400, "Nav izdevies nolasīt prasību dokumentus.")

    req_structured = ai_extract_requirements(req_text)

    # -------- CANDIDATES --------
    final_comp = ""

    for f in candidates:
        check_size(f)
        data = await f.read()

        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(data)
        tmp.close()

        cand_text = ""

        try:
            files = extract_zip_files(tmp.name) if f.filename.lower().endswith(".zip") else [tmp.name]
            classified = classify_candidate_files(files)

            # Teksts
            for p in classified["text_files"]:
                if p.lower().endswith(".pdf"):
                    cand_text += vision_extract_pdf(p)
                else:
                    cand_text += extract_docx_text(p)

            # Fakti
            if classified["excel_files"]:
                cand_text += "\n\nFinanšu pielikumi iesniegti (Excel faili)."
            if classified["signature_files"]:
                cand_text += "\n\nPiedāvājums ir parakstīts (EDOC / ASiC konteiners)."

        finally:
            for p in files:
                if os.path.exists(p):
                    os.unlink(p)
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

        comp = ai_compare(req_structured, cand_text)
        final_comp += f"\n\n=== {f.filename} ===\n{comp}"

    # -------- OUTPUT --------
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/report_{ts}.html"

    with open(path, "w", encoding="utf-8") as f:
        f.write(build_html(req_structured, final_comp))

    return {"status": "ok", "url": f"/download/{Path(path).name}"}


@app.get("/download/{filename}")
async def download(filename: str):
    filename = filename.strip('"')
    path = f"/tmp/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Fails nav atrasts.")
    return FileResponse(path, media_type="text/html")
