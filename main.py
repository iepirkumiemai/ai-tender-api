import os
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ==============================
# Import modules
# ==============================
from edoc_extractor import is_edoc, unpack_edoc, EdocError
from dropbox_client import DropboxClient
from document_parser import DocumentParser, DocumentParserError
from ai_comparison import AIComparisonEngine

# ==============================
# FastAPI init
# ==============================
app = FastAPI(
    title="AI Tender Analyzer API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,   # FIXED — the correct name!
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================
# Dropbox init
# ==============================
DROPBOX_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")
if not DROPBOX_TOKEN:
    raise RuntimeError("Environment variable DROPBOX_ACCESS_TOKEN is missing.")

dropbox_client = DropboxClient(DROPBOX_TOKEN)

@app.get("/dropbox/tree")
async def dropbox_tree(path: str = Query("")):
    try:
        files = dropbox_client.list_tree(path)
        return JSONResponse({"status": "ok", "files": files})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/dropbox/download")
async def dropbox_download(path: str):
    try:
        local_path = dropbox_client.download_file(path)
        return JSONResponse({"status": "ok", "local_path": local_path})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# ==============================
# AI Engine
# ==============================
ai_engine = AIComparisonEngine()

# ==============================
# Debug extract
# ==============================
@app.post("/debug/extract")
async def debug_extract(file: UploadFile = File(...)):
    tmp_path = Path(f"/tmp/{file.filename}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        data = DocumentParser.extract(tmp_path)
        return {
            "filename": data["filename"],
            "type": data["type"],
            "text_preview": data["text"][:5000],
        }
    except DocumentParserError as e:
        return {"error": str(e)}

# ==============================
# Debug EDOC
# ==============================
@app.post("/debug/edoc")
async def debug_edoc(file: UploadFile = File(...)):
    tmp_path = Path(f"/tmp/{file.filename}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        inner_files = unpack_edoc(tmp_path)
        return {"filename": file.filename, "inner_files": [p.name for p in inner_files]}
    except EdocError as e:
        return {"error": str(e)}

# ==============================
# Main Compare
# ==============================
@app.post("/ai-tender/compare")
async def compare(
    requirements: UploadFile = File(...),
    candidate_docs: UploadFile = File(...)
):
    req_path = Path(f"/tmp/{requirements.filename}")
    with open(req_path, "wb") as f:
        f.write(await requirements.read())

    cand_path = Path(f"/tmp/{candidate_docs.filename}")
    with open(cand_path, "wb") as f:
        f.write(await candidate_docs.read())

    try:
        result = ai_engine.analyze(req_path, cand_path)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# ==============================
# Health
# ==============================
@app.get("/health")
async def health():
    return {"status": "ok"}
