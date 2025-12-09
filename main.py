import os
import tempfile
import zipfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

app = FastAPI(
    title="ai-tender-api",
    version="0.3.0",
    description="AI Tender dokumentu apstrādes un failu detektora modulis"
)

@app.get("/")
async def root():
    return {"status": "OK", "service": "ai-tender-api"}


@app.get("/health")
async def health():
    return JSONResponse({"health": "UP"})


# ===========================
# FAILU TIPU DETEKTORS
# ===========================
def detect_file_type(file_path: str, filename: str):
    ext = filename.lower().split('.')[-1]

    # 1. Primārā klasifikācija pēc paplašinājuma
    if ext == "pdf":
        return "pdf"

    if ext == "docx":
        return "docx"

    if ext == "doc":
        return "doc"

    if ext == "txt":
        return "txt"

    if ext == "csv":
        return "csv"

    if ext == "zip":
        return "zip"

    if ext == "edoc":
        return "edoc"

    # 2. Sekundārā klasifikācija pēc faila iekšējās struktūras
    # ZIP/EDOC pārbaude
    try:
        if zipfile.is_zipfile(file_path):
            # EDOC parasti satur specificētus XML failus
            with zipfile.ZipFile(file_path, 'r') as z:
                names = z.namelist()
                if any("XML" in n.upper() for n in names):
                    return "edoc"
            return "zip"
    except:
        pass

    # 3. PDF signatūra (%PDF)
    try:
        with open(file_path, "rb") as f:
            header = f.read(5)
            if header == b"%PDF-":
                return "pdf"
    except:
        pass

    # 4. DOC signatūra (OLE2, sākas ar D0 CF 11 E0)
    try:
        with open(file_path, "rb") as f:
            header = f.read(8)
            if header.startswith(b"\xD0\xCF\x11\xE0"):
                return "doc"
    except:
        pass

    return "unknown"


# ===========================
# FAILU AUGŠUPIELĀDE + TIPU NOTEIKŠANA
# ===========================
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    temp_dir = tempfile.mkdtemp(prefix="uploaded_")
    file_path = os.path.join(temp_dir, file.filename)

    # Saglabājam failu
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    file_type = detect_file_type(file_path, file.filename)

    return {
        "status": "OK",
        "filename": file.filename,
        "type": file_type,
        "size_bytes": len(content),
        "temp_dir": temp_dir,
        "saved_to": file_path
    }
