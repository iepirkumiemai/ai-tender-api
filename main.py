import os
import tempfile
import zipfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

# ======================
#    PDF / DOCX / TXT
# ======================
from pdfminer.high_level import extract_text as pdf_extract
import mammoth

# ======================
#    OpenAI
# ======================
from openai import OpenAI
import json


# ======================
#   INIT
# ======================

app = FastAPI(
    title="ai-tender-api",
    version="1.1.0",
    description="Tenderu dokumentu analīzes API (Railway-safe)"
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ======================
#   HEALTH
# ======================

@app.get("/")
async def root():
    return {"status": "OK", "service": "ai-tender-api"}

@app.get("/health")
async def health():
    return JSONResponse({"health": "UP"})


# ======================
#   FAILA TIPS
# ======================

def detect_file_type(file_path: str, filename: str):
    ext = filename.lower().split(".")[-1]

    if ext in ["pdf", "docx", "txt", "zip", "edoc"]:
        return ext

    try:
        if zipfile.is_zipfile(file_path):
            with zipfile.ZipFile(file_path, 'r') as z:
                names = z.namelist()
                if any("XML" in x.upper() for x in names):
                    return "edoc"
            return "zip"
    except:
        pass

    try:
        with open(file_path, "rb") as f:
            if f.read(5) == b"%PDF-":
                return "pdf"
    except:
        pass

    return "unknown"


# ======================
#   ZIP / EDOC EXTRACT
# ======================

def extract_zip_or_edoc(file_path: str):
    extract_dir = tempfile.mkdtemp(prefix="extracted_")
    with zipfile.ZipFile(file_path, 'r') as z:
        z.extractall(extract_dir)

    files = []
    for root, dirs, filenames in os.walk(extract_dir):
        for name in filenames:
            files.append(os.path.join(root, name))

    return extract_dir, files


# ======================
#   TEKSTA EKSTRAKCIJA
# ======================

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
        with open(path, "rb") as f:
            raw = f.read()
            return raw.decode("utf-8", errors="ignore")
    except Exception as e:
        return f"[TXT ERROR] {e}"


def extract_text_by_type(path: str, file_type: str):
    if file_type == "pdf":
        return extract_pdf(path)
    if file_type == "docx":
        return extract_docx(path)
    if file_type == "txt":
        return extract_txt(path)
    return ""


def extract_all_texts(files: list):
    results = {}
    for f in files:
        ext = f.lower().split(".")[-1]
        if ext in ["pdf", "docx", "txt"]:
            results[f] = extract_text_by_type(f, ext)
    return results


# ======================
#   /UPLOAD
# ======================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    temp_dir = tempfile.mkdtemp(prefix="uploaded_")
    save_path = os.path.join(temp_dir, file.filename)

    with open(save_path, "wb") as f:
        data = await file.read()
        f.write(data)

    file_type = detect_file_type(save_path, file.filename)

    response = {
        "status": "OK",
        "filename": file.filename,
        "type": file_type,
        "size_bytes": len(data),
        "saved_to": save_path,
        "temp_dir": temp_dir
    }

    # ZIP & EDOC extraction
    if file_type in ["zip", "edoc"]:
        extract_dir, extracted_files = extract_zip_or_edoc(save_path)
        response["extracted_dir"] = extract_dir
        response["extracted_files"] = extracted_files
        response["texts"] = extract_all_texts(extracted_files)

    # Single (PDF / DOCX / TXT)
    if file_type in ["pdf", "docx", "txt"]:
        response["text"] = extract_text_by_type(save_path, file_type)

    return response


# ======================
#   AI ANALĪZE
# ======================

def ai_analyze(tender_text: str, candidate_docs: dict):

    docs_str = "\n\n".join(
        f"FILE: {k}\nCONTENT:\n{v}"
        for k, v in candidate_docs.items()
    )

    prompt = f"""
Tu esi profesionāls iepirkumu eksperts.
Analizē kandidāta dokumentus atbilstoši nolikumam.

Nolikums:
{tender_text}

Kandidāta dokumenti:
{docs_str}

Izveido JSON ar:
- summary
- score (Atbilst / Daļēji atbilst / Neatbilst)
- requirements [...]
- risks [...]
- missing_documents [...]
- recommendations [...]

Atbildi tikai JSON formātā.
"""

    result = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "Tu esi profesionāls iepirkumu analītiķis."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        max_tokens=5000
    )

    return json.loads(result.choices[0].message.content)


@app.post("/analyze")
async def analyze(tender_text: str, candidate_docs: dict):
    return ai_analyze(tender_text, candidate_docs)
