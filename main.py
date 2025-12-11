import os
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ==========================
# Importē moduļus
# ==========================
from edoc_extractor import is_edoc, unpack_edoc, EdocError
from dropbox_client import DropboxClient
from document_parser import DocumentParser, DocumentParserError
from ai_comparison import AIComparisonEngine


# ==========================
# FastAPI inicializācija
# ==========================
app = FastAPI(
    title="AI Tender Analyzer API",
    version="3.1.0-json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================
# Dropbox inicializācija
# ==========================
DROPBOX_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")
if not DROPBOX_TOKEN:
    raise RuntimeError("Environment variable DROPBOX_ACCESS_TOKEN is missing.")

dropbox_client = DropboxClient(DROPBOX_TOKEN)


@app.get("/dropbox/tree")
async def dropbox_tree(path: str = Query("")):
    try:
        files = dropbox_client.list_tree(path)
        return JSONResponse(
            content={"status": "ok", "files": files},
            media_type="application/json",
            indent=2
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
            indent=2
        )


@app.get("/dropbox/download")
async def dropbox_download(path: str):
    try:
        local_path = dropbox_client.download_file(path)
        return JSONResponse(
            content={"status": "ok", "local_path": local_path},
            media_type="application/json",
            indent=2
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
            indent=2
        )


# ==========================
# AI Salīdzināšanas dzinējs
# ==========================
ai_engine = AIComparisonEngine()


# ==========================
# DEBUG — Ekstrakcijas tests
# ==========================
@app.post("/debug/extract")
async def debug_extract(file: UploadFile = File(...)):
    tmp_path = Path(f"/tmp/{file.filename}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        parsed = DocumentParser.extract(tmp_path)
        preview = parsed.get("text", "")[:5000]
        return JSONResponse(
            content={
                "filename": parsed.get("filename"),
                "type": parsed.get("type"),
                "text_preview": preview
            },
            media_type="application/json",
            indent=2
        )
    except DocumentParserError as e:
        return JSONResponse(
            content={"error": str(e)},
            media_type="application/json",
            indent=2
        )


# ==========================
# DEBUG — EDOC satura pārbaude
# ==========================
@app.post("/debug/edoc")
async def debug_edoc(file: UploadFile = File(...)):
    tmp_path = Path(f"/tmp/{file.filename}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        files = unpack_edoc(tmp_path)
        return JSONResponse(
            content={"filename": file.filename, "inner_files": [p.name for p in files]},
            media_type="application/json",
            indent=2
        )
    except EdocError as e:
        return JSONResponse(
            content={"error": str(e)},
            media_type="application/json",
            indent=2
        )


# ==========================
# GALVENAIS — AI Tender Salīdzinājums (JSON only)
# ==========================
@app.post("/ai-tender/compare")
async def compare(
    requirements: UploadFile = File(...),
    candidate_docs: UploadFile = File(...)
):
    # Saglabā prasību failu
    req_path = Path(f"/tmp/{requirements.filename}")
    with open(req_path, "wb") as f:
        f.write(await requirements.read())

    # Saglabā kandidāta failu
    cand_path = Path(f"/tmp/{candidate_docs.filename}")
    with open(cand_path, "wb") as f:
        f.write(await candidate_docs.read())

    try:
        result = ai_engine.analyze(req_path, cand_path)
        return JSONResponse(
            content=result,
            media_type="application/json",
            indent=2
        )

    except DocumentParserError as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Parser error: {str(e)}"},
            indent=2
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"AI comparison error: {str(e)}"},
            indent=2
        )


# ==========================
# HEALTH CHECK
# ==========================
@app.get("/health")
async def health():
    return JSONResponse(
        content={
            "status": "ok",
            "mode": "json-only",
            "version": "3.1.0",
        },
        media_type="application/json",
        indent=2
    )
