import os
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import JSONResponse

# ============================================
# CORS — KRITISKI SVARĪGI WORDPRESS FRONTENDAM
# ============================================
from fastapi.middleware.cors import CORSMiddleware

# ======================================================
# 0. Importē visus moduļus (EDOC, Dropbox, Parseri, AI)
# ======================================================
from edoc_extractor import is_edoc, unpack_edoc, EdocError
from dropbox_client import DropboxClient
from document_parser import DocumentParser, DocumentParserError
from ai_comparison import AIComparisonEngine


# ======================================================
# FastAPI inicializācija
# ======================================================
app = FastAPI(
    title="AI Tender Analyzer API",
    version="1.0.0"
)

# ======================================================
# CORS MIDDLEWARE — obligāti nepieciešams WP front-endam
# ======================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # atļaujam WordPress frontendam piekļūt API
    allow_credentials=True,
    allow_methods=["*"],           # GET, POST, OPTIONS utt.
    allow_headers=["*"],           # viss, arī form-data
)


# ======================================================
# 1. DROPBOX inicializācija
# ======================================================
DROPBOX_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")

if not DROPBOX_TOKEN:
    raise RuntimeError("Environment variable DROPBOX_ACCESS_TOKEN is missing.")

dropbox_client = DropboxClient(DROPBOX_TOKEN)


@app.get("/dropbox/tree")
async def dropbox_tree(path: str = Query("")):
    """
    Atgriež pilnu Dropbox mapju koku (rekursīvi).
    """
    try:
        files = dropbox_client.list_tree(path)
        return JSONResponse({"status": "ok", "files": files})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/dropbox/download")
async def dropbox_download(path: str):
    """
    Lejupielādē failu no Dropbox un saglabā to pagaidu direktorijā.
    """
    try:
        local_path = dropbox_client.download_file(path)
        return JSONResponse({"status": "ok", "local_path": local_path})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ======================================================
# 2. AI SALĪDZINĀŠANAS DZINĒJS (OpenAI)
# ======================================================
ai_engine = AIComparisonEngine()


# ======================================================
# 3. DEBUG ENDPOINT — jebkura faila pilnu ekstrakcijas tests
# ======================================================
@app.post("/debug/extract")
async def debug_extract(file: UploadFile = File(...)):
    """
    Testē jebkura faila pilnu ekstrakciju (PDF, DOCX, ZIP, EDOC, TXT).
    """
    tmp_path = Path(f"/tmp/{file.filename}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        data = DocumentParser.extract(tmp_path)
        return {
            "filename": data["filename"],
            "type": data["type"],
            "text_preview": data["text"][:5000]
        }
    except DocumentParserError as e:
        return {"error": str(e)}


# ======================================================
# 4. DEBUG ENDPOINT — EDOC iekšējās struktūras testa režīms
# ======================================================
@app.post("/debug/edoc")
async def debug_edoc(file: UploadFile = File(...)):
    tmp_path = Path(f"/tmp/{file.filename}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        inner_files = unpack_edoc(tmp_path)
    except EdocError as e:
        return {"filename": file.filename, "error": str(e)}

    return {
        "filename": file.filename,
        "inner_files": [p.name for p in inner_files]
    }


# ======================================================
# 5. GALVENAIS ENDPOINTS — AI SALĪDZINĀŠANA
# ======================================================
@app.post("/ai-tender/compare")
async def compare(
    requirements: UploadFile = File(...),
    candidate_docs: UploadFile = File(...)
):
    """
    Pilnais AI Tender salīdzināšanas process:
    1. Nolasām failus
    2. Ekstrahējam saturu (PDF, DOCX, ZIP, EDOC utt.)
    3. Sadalām prasības
    4. Salīdzinām ar kandidāta dokumentiem
    5. Ģenerējam summary + analīzi + HTML tabulu
    """

    # -- Saglabā prasību dokumentu --
    req_path = Path(f"/tmp/{requirements.filename}")
    with open(req_path, "wb") as f:
        f.write(await requirements.read())

    # -- Saglabā kandidāta dokumentus --
    cand_path = Path(f"/tmp/{candidate_docs.filename}")
    with open(cand_path, "wb") as f:
        f.write(await candidate_docs.read())

    # -- AI salīdzināšana --
    try:
        result = ai_engine.analyze(req_path, cand_path)
    except DocumentParserError as e:
        return JSONResponse(status_code=500, content={"error": f"Parser error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"AI comparison error: {str(e)}"})

    return result


# ======================================================
# 6. HEALTH CHECK
# ======================================================
@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "ai-tender-analyzer"})
