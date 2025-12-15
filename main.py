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
from pdf2image import convert_from_path
from PIL import Image

# =======================
# INIT
# =======================

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – Stable Vision Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =======================
# TEXT EXTRACTORS
# =======================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip() if text else ""


def extract_docx(path: str) -> str:
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""


def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.lower().endswith((".xml", ".txt")):
                    try:
                        text += clean(z.read(name).decode(errors="ignore"))
                    except Exception:
                        pass
    except Exception:
        pass
    return text


# =======================
# VISION OCR (PDF → TEXT)
# =======================

def vision_ocr_pdf(pdf_path: str) -> str:
    """
    STABILA Vision OCR:
    - PDF → images
    - images → GPT-4o Vision
    - nekad nemet exception
    """

    try:
        images = convert_from_path(pdf_path, dpi=200)
    except Exception:
        return ""

    if not images:
        return ""

    text = ""
    CHUNK = 6

    for i in range(0, len(images), CHUNK):
        batch = images[i:i + CHUNK]

        content = [{
            "type": "input_text",
            "text": f"""
You are an expert OCR engine for legal and tender documents.

Extract ALL text exactly as it appears.
Preserve:
- headings
- tables (Markdown)
- lists
- numbering
- layout

Rules:
- Do NOT summarize
- Do NOT omit text
- Mark unclear parts as [unclear]

Pages {i+1}-{i+len(batch)}.
Output Markdown only.
"""
        }]

        for img in batch:
            buf = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            img.save(buf.name)
            with open(buf.name, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            os.unlink(buf.name)

            content.append({
                "type": "input_image",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high"
                }
            })

        try:
            r = client.responses.create(
                model="gpt-4o",
                input=[{"role": "user", "content": content}],
                max_output_tokens=4096
            )
            text += r.output_text or ""
        except Exception:
            continue

    return text


# =======================
# ZIP HANDLER
# =======================

def extract_zip(path: str) -> list[tuple[str, bytes]]:
    files = []
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if not name.endswith("/"):
                    try:
                        files.append((name, z.read(name)))
                    except Exception:
                        pass
    except Exception:
        pass
    return files


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
    return r.output_text or ""


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
    return r.output_text or ""


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

    # ---------- REQUIREMENTS ----------
    for f in requirements:
        data = await f.read()
        name = f.filename.lower()

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        if name.endswith(".docx"):
            req_text += extract_docx(tmp_path)

        elif name.endswith(".edoc"):
            req_text += extract_edoc(tmp_path)

        elif name.endswith(".pdf"):
            req_text += vision_ocr_pdf(tmp_path)

        elif name.endswith(".zip"):
            for fn, b in extract_zip(tmp_path):
                with tempfile.NamedTemporaryFile(delete=False) as zf:
                    zf.write(b)
                    zp = zf.name

                if fn.lower().endswith(".docx"):
                    req_text += extract_docx(zp)
                elif fn.lower().endswith(".pdf"):
                    req_text += vision_ocr_pdf(zp)
                elif fn.lower().endswith((".txt", ".xml")):
                    try:
                        req_text += clean(b.decode(errors="ignore"))
                    except Exception:
                        pass

                os.unlink(zp)

        os.unlink(tmp_path)

    if not req_text.strip():
        raise HTTPException(400, "Neizdevās nolasīt prasību dokumentus.")

    req_structured = ai_extract_requirements(req_text)

    # ---------- CANDIDATES ----------
    final_comp = ""

    for f in candidates:
        data = await f.read()
        name = f.filename.lower()
        cand_text = ""

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        if name.endswith(".pdf"):
            cand_text += vision_ocr_pdf(tmp_path)

        elif name.endswith(".zip"):
            for fn, b in extract_zip(tmp_path):
                with tempfile.NamedTemporaryFile(delete=False) as zf:
                    zf.write(b)
                    zp = zf.name

                if fn.lower().endswith(".pdf"):
                    cand_text += vision_ocr_pdf(zp)
                elif fn.lower().endswith(".docx"):
                    cand_text += extract_docx(zp)
                elif fn.lower().endswith((".txt", ".xml")):
                    try:
                        cand_text += clean(b.decode(errors="ignore"))
                    except Exception:
                        pass

                os.unlink(zp)

        os.unlink(tmp_path)

        comp = ai_compare(req_structured, cand_text)
        final_comp += f"\n\n=== {f.filename} ===\n{comp}"

    # ---------- OUTPUT ----------
    t = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/report_{t}.html"

    with open(path, "w", encoding="utf-8") as f:
        f.write(build_html(req_structured, final_comp))

    return {"status": "ok", "url": f"/download/{Path(path).name}"}


@app.get("/download/{filename}")
async def download(filename: str):
    path = f"/tmp/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Fails nav atrasts.")
    return FileResponse(path, media_type="text/html")
