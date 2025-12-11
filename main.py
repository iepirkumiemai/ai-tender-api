from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ==========================================================
#   AI Tender Engine — A Variant (Stable JSON-only Base)
# ==========================================================

app = FastAPI(
    title="AI Tender Engine — Stable Base",
    version="0.1.1",
    description="Stable JSON-only API base (no AI, no parsing)."
)

# ----------------------------------------------------------
# CORS support (WordPress / any frontend)
# ----------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------
# Health check endpoint
# ----------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.1",
        "mode": "json-only",
        "message": "Serveris darbojas. Gatavs darbam."
    }

# ----------------------------------------------------------
# Main comparison endpoint — JSON only
# ----------------------------------------------------------
@app.post("/compare_files")
async def compare_files(
    requirements: UploadFile = File(...),
    candidates: UploadFile = File(...)
):
    # Save requirement file
    req_path = Path(f"/tmp/{requirements.filename}")
    with open(req_path, "wb") as f:
        f.write(await requirements.read())

    # Save candidate file
    cand_path = Path(f"/tmp/{candidates.filename}")
    with open(cand_path, "wb") as f:
        f.write(await candidates.read())

    # JSON response (no indent because FastAPI does not support it)
    return JSONResponse(
        content={
            "status": "ok",
            "requirements_file": req_path.name,
            "candidate_file": cand_path.name,
            "message": "A-Variant JSON API strādā. Varam pievienot AI loģiku."
        }
    )
