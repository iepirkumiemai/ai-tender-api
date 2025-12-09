import os
import tempfile
import zipfile
from typing import Dict

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

import mammoth
from pdfminer.high_level import extract_text

app = FastAPI(title="AI-Tender-API", version="1.0")


# ================================
# 1. Helper: EDOC extraction
# ================================
def extract_edoc(path: str) -> Dict:
    results = {
        "documents": [],
        "xml": [],
        "raw_files": []
    }

    with zipfile.ZipFile(path, 'r') as z:
        with tempfile.TemporaryDirectory() as tmpdir:
            z.extractall(tmpdir)

            for root, dirs, files in os.walk(tmpdir):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    ext = filename.lower().split(".")[-1]

                    # XML files
                    if ext == "xml":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                        except:
                            content = ""

                        results["xml"].append({
                            "filename": filename,
                            "content": content
                        })
                        continue

                    # TXT files
                    if ext == "txt":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except:
                            text = ""

                        results["documents"].append({
                            "filename": filename,
                            "text": text
                        })
                        continue

                    # DOCX files
                    if ext == "docx":
                        try:
                            with open(full_path, "rb") as f:
                                doc = mammoth.convert_to_markdown(f).value
                        except:
                            doc = ""

                        results["documents"].append({
                            "filename": filename,
                            "text": doc
                        })
                        continue

                    # PDF files
                    if ext == "pdf":
                        try:
                            text = extract_text(full_path)
                        except:
                            text = ""

                        results["documents"].append({
                            "filename": filename,
                            "text": text
                        })
                        continue

                    # Unknown files
                    results["raw_files"].append({
                        "filename": filename,
                        "path": full_path
                    })

    return results


# ================================
# 2. Helper: PDF extraction
# ================================
def extract_pdf(path: str) -> str:
    try:
        return extract_text(path)
    except:
        return ""


# ================================
# 3. Helper: DOCX extraction
# ================================
def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return mammoth.convert_to_markdown(f).value
    except:
        return ""


# ================================
# 4. File processor — universal
# ================================
def process_file(file_path: str, ext: str):
    ext = ext.lower()

    if ext == "pdf":
        return {
            "file_type": "pdf",
            "text": extract_pdf(file_path)
        }

    if ext == "docx":
        return {
            "file_type": "docx",
            "text": extract_docx(file_path)
        }

    if ext == "edoc":
        edoc_data = extract_edoc(file_path)
        return {
            "file_type": "edoc",
            "documents": edoc_data["documents"],
            "xml": edoc_data["xml"],
            "raw_files": edoc_data["raw_files"]
        }

    # Unknown file
    return {
        "file_type": ext,
        "error": "Unsupported file type"
    }


# ================================
# 5. API endpoint: status
# ================================
@app.get("/api/status")
async def status():
    return {"status": "OK", "service": "ai-tender-api"}


# ================================
# 6. API endpoint: file upload
# ================================
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename
    ext = filename.split(".")[-1].lower()

    # Save temp file
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # Process file
    result = process_file(tmp_path, ext)

    return JSONResponse({
        "filename": filename,
        "extension": ext,
        "result": result
    })
