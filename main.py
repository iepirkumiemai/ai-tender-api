import os
import tempfile
import zipfile
import datetime
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI
from pdfminer.high_level import extract_text
from docx import Document

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===========================
# HELPERS
# ===========================

def clean(text):
    if not text:
        return ""
    return text.replace("\x00", "").strip()

def extract_pdf(path):
    try:
        return clean(extract_text(path))
    except:
        return ""

def extract_docx(path):
    try:
        doc = Document(path)
        return "\n".join([p.text for p in doc.paragraphs])
    except:
        return ""

def extract_edoc(path):
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.lower().endswith((".xml", ".txt")):
                    text += clean(z.read(name).decode(errors="ignore"))
    except:
        pass
    return text

def extract_zip(path):
    results = {}

    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(z.read(name))
                tmp_path = tmp.name

            if name.lower().endswith(".pdf"):
                results[name] = extract_pdf(tmp_path)

            elif name.lower().endswith(".docx"):
                results[name] = extract_docx(tmp_path)

            elif name.lower().endswith(".edoc"):
                results[name] = extract_edoc(tmp_path)

            elif name.lower().endswith(".txt"):
                try:
                    results[name] = clean(z.read(name).decode(errors="ignore"))
                except:
                    results[name] = ""

            os.unlink(tmp_path)

    return results


# ======================================
#   GPT FUNCTIONS
# ======================================

def ai_extract_requirements(text):
    prompt = f"""
Izvelc VISAS prasības no dokumenta. Saglabā secību.
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

    resp = client.responses.create(
        model="gpt-4o",
        input=prompt
    )

    return resp.output_text


def ai_compare(req_json, candidate_text):
    prompt = f"""
Salīdzini prasības ar kandidāta dokumentiem.

Katru prasību izvērtē:
- Atbilst
- Daļēji atbilst
- Neatbilst

Formāts:

[
  {{
    "prasība": "...",
    "statuss": "Atbilst / Daļēji atbilst / Neatbilst",
    "pamatojums": "..."
  }}
]

Prasības:
{req_json}

Kandidāta dokumenti:
{candidate_text}
"""

    resp = client.responses.create(
        model="gpt-4o",
        input=prompt
    )

    return resp.output_text


# ======================================
#   HTML BUILDER
# ======================================

def build_html(requirements, comparisons, filename):
    html = f"""
<html><head>
<meta charset='UTF-8'>
<style>
body {{ font-family: Arial; padding: 20px; }}
.req {{ margin-bottom: 20px; padding: 10px; border:1px solid #ccc; }}
pre {{ white-space: pre-wrap; }}
</style>
</head><body>

<h1>Tendera analīzes atskaite</h1>
<p><b>Faila nosaukums:</b> {filename}</p>

<h2>Prasību saraksts</h2>
<pre>{requirements}</pre>

<h2>Kandidāta salīdzināšana</h2>
<pre>{comparisons}</pre>

</body></html>
"""
    return html


# ======================================
#              ENDPOINT
# ======================================

@app.post("/analyze")
async def analyze(requirements: list[UploadFile] = File(...),
                  candidates: list[UploadFile] = File(...)):

    # 1) Read requirements
    req_text = ""

    for f in requirements:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(await f.read())
        tmp.close()

        name = f.filename.lower()

        if name.endswith(".pdf"):
            req_text += extract_pdf(tmp.name)
        elif name.endswith(".docx"):
            req_text += extract_docx(tmp.name)
        elif name.endswith(".edoc"):
            req_text += extract_edoc(tmp.name)
        elif name.endswith(".zip"):
            parts = extract_zip(tmp.name)
            for t in parts.values():
                req_text += t

        os.unlink(tmp.name)

    if not req_text.strip():
        raise HTTPException(400, "Prasību dokumentu nevarēja nolasīt.")

    req_structured = ai_extract_requirements(req_text)

    # 2) Candidate evaluation
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

    # 3) Produce HTML report
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/report_{timestamp}.html"

    html = build_html(req_structured, final_comp, "Tender Analysis")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return {"status": "ok", "url": f"/download/{Path(path).name}"}


@app.get("/download/{filename}")
async def download(filename: str):
    path = f"/tmp/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Fails nav atrasts.")
    return FileResponse(path, media_type="text/html")
