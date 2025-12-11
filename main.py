from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(
    title="AI Tender Engine – Stable Base",
    version="0.1.0",
    description="Stable JSON-only API base (no AI, no parsing)."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "mode": "json-only"
    }

@app.post("/compare_files")
async def compare_files(
    requirements: UploadFile = File(...),
    candidates: UploadFile = File(...)
):
    # Save both files for debugging
    req_path = Path(f"/tmp/{requirements.filename}")
    with open(req_path, "wb") as f:
        f.write(await requirements.read())

    cand_path = Path(f"/tmp/{candidates.filename}")
    with open(cand_path, "wb") as f:
        f.write(await candidates.read())

    # Return basic JSON (no AI logic)
    return JSONResponse(
        {
            "status": "ok",
            "requirements_file": req_path.name,
            "candidate_file": cand_path.name,
            "message": "Base API works. Ready for AI integration."
        },
        indent=2
    )
