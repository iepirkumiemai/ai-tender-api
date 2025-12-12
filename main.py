import os
import tempfile
import zipfile
import datetime
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import mammoth
from pdfminer.high_level import extract_text

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
#               HELPERS: FILE EXTRACTION
# ---------------------------------------------------------

def clean(text):
    if not text:
        return ""
    return text.replace("\x00", "").strip()

def extract_pdf(path: str) -> str:
    try:
        return clean(extract_text(path))
    except:
        return ""

def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
            return clean(result.value)
    except:
        return ""

def extract_edoc(path: str) -> str:
    text = ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.lower().endswith((".xml", ".txt")):
                    text += clean(z.read(name).decode(errors="ignore"))
    except:
        pass
    return text

def extract_zip(path: str) -> dict:
    """
    Returns {filename: extracted_text}
    """
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


# ---------------------------------------------------------
#            GPT-4o: REQUIREMENTS EXTRACTION
# ---------------------------------------------------------

def ai_extract_requirements(text: str) -> list:
    prompt = f"""
Izanalizē turpmāko iepirkuma prasību tekstu un izvelc VISAS prasības tādā secībā,
kādā tās parādās dokumentā. Neizdomā nekādas kategorijas.
Struktūra:

[
  {{
    "prasība": "...",
    "pamatojums": "..."
  }}
]

TEKSTS:
{text}
"""

    resp = client.responses.create(
        model="gpt-4o",
        input=prompt
    )

    return resp.output_text


# ---------------------------------------------------------
#        GPT-4o: REQUIREMENT vs DOCUMENT COMPARISON
# ---------------------------------------------------------

def ai_compare(req_json: str, candidate_text: str) -> str:
    prompt = f"""
Salīdzini prasības ar kandidāta dokumentiem.
Katru prasību izvērtē:

- "Atbilst"
- "Daļēji atbilst"
- "Neatbilst"

SEMANTISKAIS PAMATOJUMS obligāts. Formatēšana:

[
  {{
    "prasība": "...",
    "statuss": "Atbilst/Daļēji atbilst/Neatbilst",
    "pamatojums": "..."
  }}
]

PRASĪBAS JSON:
{req_json}

KANDIDĀTA DOKUMENTU TEKSTS:
{candidate_text}
"""

    resp = client.responses.create(
        model="gpt-4o",
        input=prompt
    )

    return resp.output_text


# ---------------------------------------------------------
#              HTML REPORT GENERATION
# ---------------------------------------------------------

def build_html(requirements, comparisons, filename):
    html = """
<html><head>
<meta charset='UTF-8'>
<style>
body { font-family: Arial; padding: 20px; }
h1 { color: #333; }
h2 { margin-top: 30px; }
.req-block { margin-bottom: 20px; padding: 10px; border:1px solid #ccc; border-radius:6px;}
.status-green { color: green; font-weight: bold; }
.status-yellow { color: orange; font-weight: bold; }
.status-red { color: red; font-weight: bold; }
pre { white-space: pre-wrap; }
</style>
</head><body>

<h1>Tendera analīzes atskaite</h1>
<p><b>Faila nosaukums:</b> """ + filename + "</p>"

    html += "<h2>Prasību saraksts</h2><pre>" + requirements + "</pre>"
    html += "<h2>Kandidāta salīdzināšana</h2><pre>" + comparisons + "</pre>"
    html += "</body></html>"

    return html


# ---------------------------------------------------------
#                    MAIN ENDPOINT
# ---------------------------------------------------------

@app.post("/analyze")
async def analyze(requirements: list[UploadFile] = File(...),
                  candidates: list[UploadFile] = File(...)):
    # -------------------------------
    # 1) READ REQUIREMENTS
    # -------------------------------
    full_requirements_text = ""

    for f in requirements:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(await f.read())
        tmp.close()

        name = f.filename.lower()

        if name.endswith(".pdf"):
            full_requirements_text += extract_pdf(tmp.name)
        elif name.endswith(".docx"):
            full_requirements_text += extract_docx(tmp.name)
        elif name.endswith(".edoc"):
            full_requirements_text += extract_edoc(tmp.name)
        elif name.endswith(".zip"):
            texts = extract_zip(tmp.name)
            for _, t in texts.items():
                full_requirements_text += t

        os.unlink(tmp.name)

    if not full_requirements_text.strip():
        raise HTTPException(400, "Neizdevās nolasīt prasību failu saturu.")

    # 2) GPT: extract requirements
    req_structured = ai_extract_requirements(full_requirements_text)

    # -------------------------------
    # 3) READ CANDIDATES
    # -------------------------------
    final_comparison = ""

    for f in candidates:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(await f.read())
        tmp.close()

        name = f.filename
        extracted = extract_zip(tmp.name)

        cand_text = "\n\n".join(extracted.values())

        os.unlink(tmp.name)

        if not cand_text.strip():
            final_comparison += f"\n\nDokuments {name}: tukšs vai nenolasāms."
            continue

        comp = ai_compare(req_structured, cand_text)
        final_comparison += f"\n\n=== {name} ===\n" + comp

    # -------------------------------
    # 4) HTML REPORT
    # -------------------------------

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"/tmp/report_{timestamp}.html"

    html = build_html(req_structured, final_comparison, "Tender Analysis")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    url = f"/download/{Path(report_path).name}"

    return {"status": "ok", "report_url": url}


# ---------------------------------------------------------
#       FILE DOWNLOAD ENDPOINT
# ---------------------------------------------------------

@app.get("/download/{filename}")
async def download(filename: str):
    path = f"/tmp/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Fails nav atrasts")
    return FileResponse(path, media_type="text/html")
