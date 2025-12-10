# ================================================
# main.py — Tender Comparison Engine v13 (HTML export)
# ================================================

import os
import zipfile
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from typing import List

import mammoth
from pdfminer.high_level import extract_text
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(
    title="AI Tender Comparison Engine",
    version="13.0",
    description="Upload requirement documents + candidate ZIPs → get HTML comparison result"
)

# =========================================================
# Helpers
# =========================================================

def clean(text: str) -> str:
    return text.replace("\x00", "").strip()


# =========================================================
# Extractors
# =========================================================

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
                if name.endswith(".xml") or name.endswith(".txt"):
                    try:
                        text += clean(z.read(name).decode(errors="ignore"))
                    except:
                        pass
    except:
        pass
    return text


def extract_zip(path: str) -> str:
    combined = ""

    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue

                tmp = tempfile.NamedTemporaryFile(delete=False)
                tmp.write(z.read(name))
                tmp_path = tmp.name
                tmp.close()

                lname = name.lower()

                if lname.endswith(".pdf"):
                    combined += extract_pdf(tmp_path)

                elif lname.endswith(".docx"):
                    combined += extract_docx(tmp_path)

                elif lname.endswith(".edoc"):
                    combined += extract_edoc(tmp_path)

                elif lname.endswith(".zip"):
                    combined += extract_zip(tmp_path)

                # always cleanup
                os.unlink(tmp_path)

    except Exception as e:
        print("ZIP extraction error:", e)

    return combined


# =========================================================
# AI — REQUIREMENTS
# =========================================================

def parse_requirements_ai(text: str) -> str:
    prompt = f"""
Tu esi profesionāls iepirkumu prasību analītiķis.

Izvelc un strukturē prasību dokumentu.

Atgriez tikai JSON šādā formā:

{{
  "requirements": [...],
  "summary": "...",
  "risks": [...],
  "key_points": [...]
}}

Dokuments:
{text}
"""
    resp = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )
    return resp.output_text


# =========================================================
# AI — CANDIDATE EVALUATION
# =========================================================

def compare_candidate_ai(requirements_json: str, candidate_text: str) -> str:
    prompt = f"""
Salīdzini kandidātu dokumentu ar prasībām.

Atgriez tikai JSON:

{{
  "status": "green | yellow | red",
  "match_score": 0-100,
  "matched": [...],
  "missing": [...],
  "risks": [...],
  "summary": "..."
}}

PRASĪBAS (JSON):
{requirements_json}

KANDIDĀTA TEKSTS:
{candidate_text}
"""

    resp = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )
    return resp.output_text


# =========================================================
# HTML BUILDER
# =========================================================

def build_html(requirements_json: str, candidates: list) -> str:
    html = """
<!DOCTYPE html>
<html lang="lv">
<head>
<meta charset="UTF-8"/>
<title>Vērtējums</title>
<style>
body { font-family: Arial, sans-serif; padding: 20px; }
h1 { color: #003366; }
h2 { color: #0055aa; }
.green { color: green; font-weight:bold; }
.yellow { color: orange; font-weight:bold; }
.red { color: red; font-weight:bold; }
.block { margin-bottom: 25px; padding: 10px; border:1px solid #ddd; border-radius:6px; }
</style>
</head>
<body>

<h1>Ieprikuma Vērtējums</h1>

<h2>Prasību analīze</h2>
<div class="block">
<pre>{}</pre>
</div>

<h2>Kandidātu rezultāti</h2>
""".format(requirements_json)

    # pievienojam katru kandidātu
    for c in candidates:
        status = c.get("evaluation", "{}")
        filename = c.get("candidate", "nezināms")

        html += f"""
<div class="block">
  <h3>Kandidāts: {filename}</h3>
  <pre>{status}</pre>
</div>
"""

    html += """
</body>
</html>
"""
    return html


# =========================================================
# MAIN ENDPOINT — HTML download
# =========================================================

@app.post("/compare_files_html")
async def compare_files_html(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):
    # =============================
    # Extract requirement text
    # =============================
    full_req_text = ""

    for f in requirements:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(await f.read())
        p = tmp.name
        tmp.close()

        name = f.filename.lower()

        if name.endswith(".pdf"):
            full_req_text += extract_pdf(p)
        elif name.endswith(".docx"):
            full_req_text += extract_docx(p)
        elif name.endswith(".edoc"):
            full_req_text += extract_edoc(p)
        elif name.endswith(".zip"):
            full_req_text += extract_zip(p)
        else:
            os.unlink(p)
            raise HTTPException(400, f"Nepareizs prasību fails: {name}")

        os.unlink(p)

    if not full_req_text.strip():
        raise HTTPException(400, "Neizdevās nolasīt prasību failu saturu.")

    # AI struktūras izveide
    req_structured = parse_requirements_ai(full_req_text)

    # =============================
    # Process candidates
    # =============================
    candidate_results = []

    for f in candidates:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(await f.read())
        p = tmp.name
        tmp.close()

        name = f.filename.lower()

        if not name.endswith(".zip"):
            os.unlink(p)
            raise HTTPException(400, f"Kandidātam jābūt ZIP: {name}")

        candidate_text = extract_zip(p)
        os.unlink(p)

        if not candidate_text.strip():
            candidate_results.append({
                "candidate": f.filename,
                "evaluation": '{"status":"red","summary":"Tukšs vai nelasāms"}'
            })
            continue

        ai_eval = compare_candidate_ai(req_structured, candidate_text)

        candidate_results.append({
            "candidate": f.filename,
            "evaluation": ai_eval
        })

    # =============================
    # Generate HTML file
    # =============================
    html = build_html(req_structured, candidate_results)

    out_path = "/tmp/tender_report.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return FileResponse(
        out_path,
        media_type="text/html",
        filename="tender_report.html"
    )
