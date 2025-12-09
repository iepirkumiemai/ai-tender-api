import os
import tempfile
import zipfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

# PDF
from pdfminer.high_level import extract_text as pdf_extract

# DOCX
import mammoth

# TXT
import chardet

# XML
from lxml import etree

# OpenAI
from openai import OpenAI
import json


# ==============================
#  INIT
# ==============================

app = FastAPI(
    title="ai-tender-api",
    version="1.0.0",
    description="Tenderu dokumentu analīzes API"
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ==============================
#  HEALTH
# ==============================

@app.get("/")
async def root():
    return {"status": "OK", "service": "ai-tender-api"}

@app.get("/health")
async def health():
    return JSONResponse({"health": "UP"})


# ==============================
#  FAILA TIPA NOTEIKŠANA
# ==============================

def detect_file_type(file_path: str, filename: str):
    ext = filename.lower().split('.')[-1]

    if ext in ["pdf", "docx", "txt", "csv", "xml", "zip", "edoc", "doc"]:
        return ext

    # Pārbaude vai ZIP
    try:
        if zipfile.is_zipfile(file_path):
            with zipfile.ZipFile(file_path, 'r') as z:
                names = z.namelist()
                if any("XML" in x.upper() for x in names):
                    return "edoc"
            return "zip"
    except:
        pass

    # PDF signatūra
    try:
        with open(file_path, "rb") as f:
            if f.read(5) == b"%PDF-":
                return "pdf"
    except:
        pass

    return "unknown"


# ==============================
#  ZIP / EDOC EKSTRAKCIJA
# ==============================

def extract_zip_or_edoc(file_path: str):
    extract_dir = tempfile.mkdtemp(prefix="extracted_")
    with zipfile.ZipFile(file_path, 'r') as z:
        z.extractall(extract_dir)

    files = []
    for root, dirs, filenames in os.walk(extract_dir):
        for name in filenames:
            files.append(os.path.join(root, name))

    return extract_dir, files


# ==============================
#  TEKSTA EKSTRAKCIJA
# ==============================

def extract_pdf(path: str):
    try:
        return pdf_extract(path)
    except Exception as e:
        return f"[PDF ERROR] {e}"

def extract_docx(path: str):
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
            return result.value
    except Exception as e:
        return f"[DOCX ERROR] {e}"

def extract_txt(path: str):
    try:
        raw = open(path, "rb").read()
        enc = chardet.detect(raw)["encoding"] or "utf-8"
        return raw.decode(enc, errors="ignore")
    except Exception as e:
        return f"[TXT ERROR] {e}"

def extract_xml(path: str):
    try:
        tree = etree.parse(path)
        return etree.tostring(tree, pretty_print=True, encoding="unicode")
    except Exception as e:
        return f"[XML ERROR] {e}"

def extract_text_by_type(path: str, file_type: str):
    if file_type == "pdf":
        return extract_pdf(path)
    if file_type == "docx":
        return extract_docx(path)
    if file_type == "txt":
        return extract_txt(path)
    if file_type == "xml":
        return extract_xml(path)
    return ""


def extract_all_texts(file_list: list):
    results = {}
    for f in file_list:
        ext = f.lower().split('.')[-1]
        if ext in ["pdf", "docx", "txt", "xml"]:
            results[f] = extract_text_by_type(f, ext)
    return results


# ==============================
#  /UPLOAD ENDPOINT
# ==============================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    temp_dir = tempfile.mkdtemp(prefix="uploaded_")
    file_path = os.path.join(temp_dir, file.filename)

    # Save
    with open(file_path, "wb") as f:
        data = await file.read()
        f.write(data)

    file_type = detect_file_type(file_path, file.filename)

    response = {
        "status": "OK",
        "filename": file.filename,
        "type": file_type,
        "size_bytes": len(data),
        "saved_to": file_path,
        "temp_dir": temp_dir
    }

    # ZIP / EDOC ekstrakcija
    if file_type in ["zip", "edoc"]:
        extract_dir, extracted_files = extract_zip_or_edoc(file_path)
        response["extracted_dir"] = extract_dir
        response["extracted_files"] = extracted_files
        response["texts"] = extract_all_texts(extracted_files)

    # Single file (PDF/DOCX/TXT/XML)
    if file_type in ["pdf", "docx", "txt", "xml"]:
        response["text"] = extract_text_by_type(file_path, file_type)

    return response


# ==============================
#  AI ANALĪZE
# ==============================

def analyze_with_ai(tender_text: str, candidate_docs: dict):

    docs_str = "\n\n".join([
        f"FILE: {k}\nCONTENT:\n{v}"
        for k, v in candidate_docs.items()
    ])

    prompt = f"""
Tu esi profesionāls iepirkumu eksperts ar 20+ gadu pieredzi.

Nolikums:
{tender_text}

Kandidāta dokumenti:
{docs_str}

Izveido JSON analīzi:
- summary
- score (Atbilst / Daļēji atbilst / Neatbilst)
- requirements: [{{
    requirement,
    status,
    evidence,
    missing,
    risk
}}]
- risks
- missing_documents
- recommendations

Atbildi tikai JSON.
"""

    resp = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "Tu esi profesionāls iepirkumu analītiķis."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        max_tokens=5000
    )

    return json.loads(resp.choices[0].message.content)


@app.post("/analyze")
async def analyze(tender_text: str, candidate_docs: dict):
    return analyze_with_ai(tender_text, candidate_docs)
