import os
import zipfile
import tempfile
import base64
import datetime
from pathlib import Path
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from openai import OpenAI
from docx import Document
from openpyxl import load_workbook

# =========================
# INIT
# =========================

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – C Stable")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TMP_DIR = "/tmp"

# =========================
# LOW LEVEL HELPERS
# =========================

def clean_text(text: str) -> str:
    return text.replace("\x00", "").strip() if text else ""


def extract_docx_bytes(data: bytes) -> str:
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        doc = Document(path)
        text = "\n".join(p.text for p in doc.paragraphs)
        return clean_text(text)
    except:
        return ""
    finally:
        try:
            os.unlink(path)
        except:
            pass


def extract_xlsx_bytes(data: bytes) -> str:
    text = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        wb = load_workbook(path, data_only=True)
        for sheet in wb:
            for row in sheet.iter_rows(values_only=True):
                row_text = " | ".join(str(c) for c in row if c is not None)
                text += row_text + "\n"
        return clean_text(text)
    except:
        return ""
    finally:
        try:
            os.unlink(path)
        except:
            pass


def extract_edoc_bytes(data: bytes) -> str:
    text = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.lower().endswith((".xml", ".txt")):
                    try:
                        text += z.read(name).decode(errors="ignore") + "\n"
                    except:
                        pass
        return clean_text(text)
    except:
        return ""
    finally:
        try:
            os.unlink(path)
        except:
            pass


def extract_zip_bytes(data: bytes) -> dict:
    """
    ZIP = konteiners
    atgriež: filename -> bytes
    """
    files = {}
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(data)
        path = tmp.name

    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if not name.endswith("/"):
                    try:
                        files[name] = z.read(name)
                    except:
                        files[name] = b""
    finally:
        os.unlink(path)

    return files


# =========================
# AI EXTRACTION (UNIVERSAL)
# =========================

def ai_extract_from_binary(filename: str, data: bytes) -> str:
    """
    Universāla ekstrakcija:
    - PDF
    - skenēts
    - nezināms formāts
    """
    b64 = base64.b64encode(data).decode()

    prompt = f"""
Tu esi precīzs dokumentu analīzes instruments.

Fails: {filename}

Uzdevums:
- Izvilkt VISU salasāmo tekstu
- Nesummēt
- Saglabāt struktūru, ja iespējams
- Ja kaut kas nav salasāms – ignorēt

BASE64:
{b64}
"""

    r = client.responses.create(
        model="gpt-4o",
        input=prompt,
        max_output_tokens=4096
    )

    return clean_text(r.output_text or "")


# =========================
# AI LOGIC
# =========================

def ai_extract_requirements(text: str) -> str:
    prompt = f"""
Izvelc VISAS iepirkuma prasības no teksta.
Nesummē, neko neizdomā.

Atgriez JSON masīvu:
[
  {{
    "prasība": "...",
    "pamatojums": "..."
  }}
]

TEKSTS:
{text}
"""
    r = client.responses.create(model="gpt-4o", input=prompt)
    return r.output_text


def ai_compare(requirements: str, candidate_text: str) -> str:
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

PRASĪBAS:
{requirements}

KANDIDĀTA SATURS:
{candidate_text}
"""
    r = client.responses.create(model="gpt-4o", input=prompt)
    return r.output_text


# =========================
# HTML
# =========================

def build_html(req: str, comp: str) -> str:
    return f"""
<html>
<head>
<meta charset="UTF-8">
<title>Tendera analīze</title>
<style>
body {{ font-family: Arial; padding: 20px; }}
pre {{ white-space: pre-wrap; background: #f4f4f4; padding: 10px; }}
</style>
</head>
<body>

<h1>Tendera analīzes atskaite</h1>

<h2>Prasības</h2>
<pre>{req}</pre>

<h2>Salīdzinājums</h2>
<pre>{comp}</pre>

</body>
</html>
"""


# =========================
# API
# =========================

@app.post("/analyze")
async def analyze(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):
    req_text = ""

    # -------- PRASĪBAS --------
    for f in requirements:
        data = await f.read()
        name = f.filename.lower()

        if name.endswith(".docx"):
            req_text += extract_docx_bytes(data)
        elif name.endswith(".xlsx"):
            req_text += extract_xlsx_bytes(data)
        elif name.endswith(".edoc"):
            req_text += extract_edoc_bytes(data)
        elif name.endswith(".zip"):
            for fn, b in extract_zip_bytes(data).items():
                req_text += ai_extract_from_binary(fn, b)
        else:
            req_text += ai_extract_from_binary(f.filename, data)

    if not req_text.strip():
        raise HTTPException(400, "Neizdevās nolasīt prasības.")

    req_structured = ai_extract_requirements(req_text)

    # -------- KANDIDĀTI --------
    final_comp = ""

    for f in candidates:
        data = await f.read()
        cand_text = ""

        if f.filename.lower().endswith(".zip"):
            for fn, b in extract_zip_bytes(data).items():
                cand_text += ai_extract_from_binary(fn, b)
        else:
            cand_text += ai_extract_from_binary(f.filename, data)

        comp = ai_compare(req_structured, cand_text)
        final_comp += f"\n\n=== {f.filename} ===\n{comp}"

    # -------- HTML --------
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{TMP_DIR}/report_{ts}.html"

    html = build_html(req_structured, final_comp)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return {
        "status": "ok",
        "download_url": f"/download/{Path(path).name}"
    }


@app.get("/download/{filename}")
async def download(filename: str):
    path = f"{TMP_DIR}/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Fails nav atrasts")
    return FileResponse(path, media_type="text/html")
