from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# =========================
# Minimalais AI Engine Mock
# (šeit tu vari likt īsto loģiku,
#  bet API nesabruks pat tukšā formā)
# =========================
def run_ai_analysis(req_path: Path, cand_path: Path):
    return {
        "status": "ok",
        "requirements_file": req_path.name,
        "candidate_file": cand_path.name,
        "analysis": "AI analysis placeholder — system stable and running."
    }

# =========================
# FastAPI inicializācija
# =========================
app = FastAPI(
    title="AI Tender Analyzer — JSON Stable",
    version="0.1.0"
)

# CORS priekš WordPress / Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Health check
# =========================
@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "mode": "json-only"}

# =========================
# Galvenais JSON salīdzināšanas endpoints
# =========================
@app.post("/ai-tender/compare")
async def compare_files(
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

    # Izsauc stabilo AI loģiku
    result = run_ai_analysis(req_path, cand_path)

    return JSONResponse(content=result, indent=2)
