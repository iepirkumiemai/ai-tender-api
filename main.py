import os
import tempfile
import zipfile
import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from openai import OpenAI
from docx import Document

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – No-PDFMiner Version")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =======================
# HELPERS
# =======================

def clean(text):
    return text.replace("\x00", "").strip() if text else ""


def extract_docx(path):
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except:
        return ""


def extract_edoc(path):
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


def extract_zip(path):
    results = {}

    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue

            ext = name.lower()
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(z.read(name))
                tmp_path = tmp.name

            if ext.endswith(".docx"):
                results[name] = extract_docx(tmp_path)

            elif ext.endswith(".edoc"):
                results[name] = extract_edoc(tmp_path)

            elif ext.endswith(".txt"):
                try:
                    results[name] = clean(z.read(name).decode(errors="ignore"))
                except:
                    results[name] = ""

            elif ext.endswith(".pdf"):
                # PDF → Vision OCR
                with open(tmp_path, "rb") as f:
                    pdf_bytes = f.read()

                vision_response = client.responses.create(
                    model="gpt-4o-mini",
                    input=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text",
                                 "text": "Extract all text from this PDF file."},
                                {
                                    "type": "input_file",
                                    "mime_type": "application/pdf",
                                    "data": pdf_bytes
                                }
                            ]
                        }
                    ]
                )

                results[name] = vision_response.output_text

            os.unlink(tmp_path)

    return results


# =======================
# GPT PROCESSING
# =======================

def ai_extract_requirements(text):
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


def ai_compare(req_json, cand_text):
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
# HTML OUTPUT
# =======================

def build_html(requirements, comparisons):
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
# API ENDPOINT
# =======================

@app.post("/analyze")
async def analyze(requirements: list[UploadFile] = File(...),
                  candidates: list[UploadFile] = File(...)):

    req_text = ""

    # =======================
    # Load requirements
    # =======================
    for f in requirements:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(await f.read())
        tmp.close()

        ext = f.filename.lower()

        if ext.endswith(".docx"):
            req_text += extract_docx(tmp.name)
        elif ext.endswith(".edoc"):
            req_text += extract_edoc(tmp.name)
        elif ext.endswith(".zip"):
            for t in extract_zip(tmp.name).values():
                req_text += t
        elif ext.endswith(".pdf"):
            with open(tmp.name, "rb") as pdf:
                pdf_bytes = pdf.read()

            vr = client.responses.create(
                model="gpt-4o-mini",
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Extract all text from this PDF."},
                            {"type": "input_file", "mime_type": "application/pdf", "data": pdf_bytes}
                        ]
                    }
                ]
            )
            req_text += vr.output_text

        os.unlink(tmp.name)

    if not req_text.strip():
        raise HTTPException(400, "Neizdevās nolasīt prasību dokumentu.")

    req_structured = ai_extract_requirements(req_text)

    # =======================
    # Load candidates
    # =======================
    final_comp = ""

    for f in candidates:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(await f.read())
        tmp.close()

        extracted = extract_zip(tmp.name)
        cand_text = "\n\n".join(extracted.values())
        os.unlink(tmp.name)

        comp = ai_compare(req_structured, cand_text)
        final_comp += f"\n\n=== {f.filename} ===\n{comp}"

    # =======================
    # Output HTML
    # =======================
    t = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/report_{t}.html"

    html = build_html(req_structured, final_comp)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return {"status": "ok", "url": f"/download/{Path(path).name}"}


@app.get("/download/{filename}")
async def download(filename: str):
    path = f"/tmp/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Fails nav atrasts.")
    return FileResponse(path, media_type="text/html")
