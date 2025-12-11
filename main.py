import os
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ==========================
# Importē moduļus (tie paši, kas strādāja toreiz)
# ==========================
from document_parser import DocumentParser, DocumentParserError
from ai_comparison import AIComparisonEngine

# ==========================
# FastAPI inicializācija
# ==========================
app = FastAPI(
    title="AI Tender Analyzer API",
    version="0.9.0-json-stable"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# AI comparison engine
# ==========================
ai_engine = AIComparisonEngine()


# ==========================
# DEBUG – vienkārša ekstrakcija
# ==========================
@app.post("/debug/extract")
async def debug_extract(file: UploadFile = File(...)):
    tmp_path = Path(f"/tmp/{file.filename}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        data = DocumentParser.extract(tmp_path)
        return JSONResponse(
            {
                "filename": data["filename"],
                "type": data["type"],
                "text_preview": data["text"][:2000]
            },
            indent=2
        )
    except DocumentParserError as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ==========================
# GALVENĀ FUNCTION – JSON AI SALĪDZINĀŠANA
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

    # Izpilda AI salīdzināšanu
    try:
        result = ai_engine.analyze(req_path, cand_path)
        return JSONResponse(result, indent=2)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ==========================
# HEALTH CHECK
# ==========================
@app.get("/health")
async def health():
    return JSONResponse(
        {"status": "ok", "version": "0.9.0-json-stable"},
        indent=2
    )
