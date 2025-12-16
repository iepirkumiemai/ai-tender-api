import os
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from document_parser import DocumentParserError
from ai_comparison import AIComparisonEngine

# ==========================
# FastAPI inicializācija
# ==========================
app = FastAPI(
    title="AI Tender Analyzer API",
    version="FINAL-ANALYZE-ENDPOINT"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# AI Engine
# ==========================
ai_engine = AIComparisonEngine()

# ==========================
# GALVENAIS ENDPOINTS
# ==========================
@app.post("/analyze")
async def analyze(
    requirements: UploadFile = File(...),
    candidate_docs: UploadFile = File(...)
):
    """
    IEEJA:
    - requirements: prasību dokuments (DOCX / PDF)
    - candidate_docs: kandidāta dokuments vai ZIP

    IZEJA:
    - ATBILST
    - MANUĀLI JĀPĀRBAUDA + pamatojumi
    - NEATBILST + pamatojumi
    """

    try:
        # --- Saglabājam failus lokāli
        req_path = Path(f"/tmp/{requirements.filename}")
        with open(req_path, "wb") as f:
            f.write(await requirements.read())

        cand_path = Path(f"/tmp/{candidate_docs.filename}")
        with open(cand_path, "wb") as f:
            f.write(await candidate_docs.read())

        # --- AI analīze
        result = ai_engine.analyze(req_path, cand_path)

        # --- TIKAI JSON
        return JSONResponse(
            status_code=200,
            content=result,
            media_type="application/json"
        )

    except DocumentParserError as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Document parsing error: {str(e)}"}
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# ==========================
# HEALTH CHECK
# ==========================
@app.get("/health")
async def health():
    return JSONResponse(
        content={
            "status": "ok",
            "endpoint": "/analyze",
            "mode": "json-only"
        }
    )
