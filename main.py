import os
import uuid
import mimetypes
from fastapi import FastAPI, UploadFile, File

app = FastAPI()


# ==============================
# ROOT ENDPOINT
# ==============================
@app.get("/")
def root():
    return {"status": "OK", "service": "ai-iepirkumi-api"}


# ==============================
# FAILA TIPA DETEKTORS
# ==============================
def detect_file_type(file_path: str):
    """
    Nosaka faila tipu pēc paplašinājuma, MIME type un magic bytes.
    Atgriež dict:
    {
        "file_type": "pdf/docx/zip/edoc/jpg/png/txt/unknown",
        "mime_type": "...",
        "magic": "25504446"
    }
    """
    # 1. MIME TYPE
    mime_type, _ = mimetypes.guess_type(file_path)
    mime_type = mime_type or "application/octet-stream"

    # 2. MAGIC BYTES
    magic = ""
    try:
        with open(file_path, "rb") as f:
            magic = f.read(8).hex()
    except:
        magic = ""

    # 3. FAILA PAPLAŠINĀJUMS
    ext = file_path.lower()

    # PDF (magic: 25504446 = %PDF)
    if ext.endswith(".pdf") or magic.startswith("25504446"):
        return {"file_type": "pdf", "mime_type": mime_type, "magic": magic}

    # DOCX (zip), bet ar .docx paplašinājumu
    if ext.endswith(".docx"):
        return {"file_type": "docx", "mime_type": mime_type, "magic": magic}

    # TXT
    if ext.endswith(".txt"):
        return {"file_type": "txt", "mime_type": mime_type, "magic": magic}

    # EDOC
    if ext.endswith(".edoc"):
        return {"file_type": "edoc", "mime_type": mime_type, "magic": magic}

    # ZIP
    if ext.endswith(".zip"):
        return {"file_type": "zip", "mime_type": mime_type, "magic": magic}

    # JPG (magic: ffd8ff)
    if magic.startswith("ffd8ff"):
        return {"file_type": "jpg", "mime_type": mime_type, "magic": magic}

    # PNG (magic: 89504e47)
    if magic.startswith("89504e47"):
        return {"file_type": "png", "mime_type": mime_type, "magic": magic}

    # UNKNOWN
    return {"file_type": "unknown", "mime_type": mime_type, "magic": magic}


# ==============================
# UPLOAD ENDPOINT
# ==============================
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    # 1. Izveido pagaidu direktoriju
    file_id = uuid.uuid4().hex
    upload_dir = f"/tmp/upload_{file_id}"
    os.makedirs(upload_dir, exist_ok=True)

    # 2. Pilns fails ceļš
    file_path = os.path.join(upload_dir, file.filename)

    # 3. Saglabā failu
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # 4. Faila tipa detektors
    file_info = detect_file_type(file_path)

    # 5. Atbilde
    return {
        "status": "uploaded",
        "filename": file.filename,
        "temp_path": file_path,
        "file_type": file_info["file_type"],
        "mime_type": file_info["mime_type"],
        "magic": file_info["magic"]
    }
