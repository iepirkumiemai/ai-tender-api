import os
import uuid
import mimetypes
from fastapi import FastAPI, UploadFile, File

# PDF ekstrakcija
from pdfminer.high_level import extract_text

app = FastAPI(title="AI Iepirkumi API", version="1.0")


# ======================================================
# ROOT ENDPOINT
# ======================================================
@app.get("/")
def root():
    return {"status": "OK", "service": "ai-iepirkumi-api"}


# ======================================================
# FAILA TIPA DETEKTORS
# ======================================================
def detect_file_type(file_path: str):
    """
    Nosaka faila tipu pēc paplašinājuma, MIME type un magic bytes.
    """
    mime_type, _ = mimetypes.guess_type(file_path)
    mime_type = mime_type or "application/octet-stream"

    # Magic bytes
    magic = ""
    try:
        with open(file_path, "rb") as f:
            magic = f.read(8).hex()
    except:
        magic = ""

    ext = file_path.lower()

    # PDF
    if ext.endswith(".pdf") or magic.startswith("25504446"):
        return {"file_type": "pdf", "mime_type": mime_type, "magic": magic}

    # DOCX
    if ext.endswith(".docx"):
        return {"file_type": "docx", "mime_type": mime_type, "magic": magic}

    # TXT
    if ext.endswith(".txt"):
        return {"file_type": "txt", "mime_type": mime_type, "magic": magic}

    # EDOC (eParaksta ZIP konteiners)
    if ext.endswith(".edoc"):
        return {"file_type": "edoc", "mime_type": mime_type, "magic": magic}

    # ZIP
    if ext.endswith(".zip"):
        return {"file_type": "zip", "mime_type": mime_type, "magic": magic}

    # JPG
    if magic.startswith("ffd8ff"):
        return {"file_type": "jpg", "mime_type": mime_type, "magic": magic}

    # PNG
    if magic.startswith("89504e47"):
        return {"file_type": "png", "mime_type": mime_type, "magic": magic}

    # Unknown
    return {"file_type": "unknown", "mime_type": mime_type, "magic": magic}


# ======================================================
# PDF EKSTRAKCIJA
# ======================================================
def extract_pdf_text(file_path: str):
    """
    Ekstrahē tekstu no PDF, izmantojot pdfminer.six.
    Ja PDF nesatur tekstu — atgriež tukšu string.
    """
    try:
        text = extract_text(file_path)
        if text and text.strip():
            return text.strip()
        return ""
    except Exception as e:
        return f"[PDF_EXTRACT_ERROR] {str(e)}"


# ======================================================
# UNIVERSĀLAIS FAILU PROCESSORS (Variants B)
# ======================================================
def process_file(file_type: str, file_path: str):
    """
    Universāls apstrādes modulis.
    Šobrīd implementēts PDF, nākamais būs DOCX un EDOC.
    """
    # PDF
    if file_type == "pdf":
        extracted_text = extract_pdf_text(file_path)
        return {"extracted_text": extracted_text}

    # DOCX — būs nākamais solis
    if file_type == "docx":
        return {"extracted_text": None, "note": "DOCX extraction module not yet implemented"}

    # EDOC — būs nākamais solis pēc DOCX
    if file_type == "edoc":
        return {"extracted_text": None, "note": "EDOC extraction module not yet implemented"}

    # ZIP — vēlāk atvērsim un analizēsim saturu
    if file_type == "zip":
        return {"extracted_text": None, "note": "ZIP extraction not yet implemented"}

    # TXT
    if file_type == "txt":
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return {"extracted_text": f.read()}
        except:
            return {"extracted_text": None, "note": "TXT read error"}

    # Attēli — nākotnē OCR
    if file_type in ["jpg", "png"]:
        return {"extracted_text": None, "note": "OCR module not yet implemented"}

    # Default
    return {"extracted_text": None, "note": "Unsupported file type"}


# ======================================================
# UPLOAD ENDPOINT (universālais variants B)
# ======================================================
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    # 1. Izveido pagaidu direktoriju
    file_id = uuid.uuid4().hex
    upload_dir = f"/tmp/upload_{file_id}"
    os.makedirs(upload_dir, exist_ok=True)

    # 2. Pilnais fails
    file_path = os.path.join(upload_dir, file.filename)

    # 3. Saglabā failu
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # 4. Atrod faila tipu
    file_info = detect_file_type(file_path)
    file_type = file_info["file_type"]

    # 5. Izpilda universālo apstrādi
    process_result = process_file(file_type, file_path)

    # 6. Atbildē viss nepieciešamais
    return {
        "status": "uploaded",
        "filename": file.filename,
        "temp_path": file_path,
        "file_type": file_info["file_type"],
        "mime_type": file_info["mime_type"],
        "magic": file_info["magic"],
        "result": process_result
    }
