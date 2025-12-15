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

MAX_FILE_SIZE_MB = 25          # drošs limits vienam failam
MAX_ZIP_FILES = 50             # cik failus max apstrādā ZIPā
VISION_MODEL = "gpt-4o-mini"   # stabils Vision OCR

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – C Variant (Stable)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =======================
# HELPERS
# =======================

def check_size(file: UploadFile):
    if file.size and file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            413,
            f"Fails '{file.filename}' ir par lielu (>{MAX_FILE_SIZE_MB} MB)"
        )


def extract_docx_text(path: str) -> str:
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""


def vision_extract_pdf(path: str) -> str:
    """
    VIENĪGA vieta, kur izmantojam Vision.
    PDF tiek sūtīts kā input_file (pareizais veids).
    """
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
    """
    Atgriež TEMP failu ceļus (PDF / DOCX)
    """
    extracted_paths = []

    with zipfile.ZipFile(path, "r") as z:
        names = [n for n in z.namelist() if not n.endswith("/")][:MAX_ZIP_FILES]

        for name in names:
            ext = name.lower()
            if not ext.endswith((".pdf", ".docx")):
                continue

            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.write(z.read(name))
            tmp.close()
            extracted_paths.append(tmp.name)

    return extracted_paths


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


def ai_compare(requirements_json: str, candidate_text: str) -> str:
    prompt = f"""
Salīdzini prasības ar kandidāta dokumentiem.

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
{requirements_json}

Kandidāta dokumenti:
{candidate_text}
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
            name = f.filename.lower()

            if name.endswith(".docx"):
                req_text += extract_docx_text(tmp.name)

            elif name.endswith(".pdf"):
                req_text += vision_extract_pdf(tmp.name)

            elif name.endswith(".zip"):
                for p in extract_zip_files(tmp.name):
                    if p.endswith(".pdf"):
                        req_text += vision_extract_pdf(p)
                    elif p.endswith(".docx"):
                        req_text += extract_docx_text(p)
                    os.unlink(p)
        finally:
            os.unlink(tmp.name)

    if not req_text.strip():
        raise HTTPException(400, "Neizdevās nolasīt prasību dokumentus.")

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
            name = f.filename.lower()

            if name.endswith(".pdf"):
                cand_text = vision_extract_pdf(tmp.name)

            elif name.endswith(".docx"):
                cand_text = extract_docx_text(tmp.name)

            elif name.endswith(".zip"):
                for p in extract_zip_files(tmp.name):
                    if p.endswith(".pdf"):
                        cand_text += vision_extract_pdf(p)
                    elif p.endswith(".docx"):
                        cand_text += extract_docx_text(p)
                    os.unlink(p)
        finally:
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
    path = f"/tmp/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Fails nav atrasts.")
    return FileResponse(path, media_type="text/html")
