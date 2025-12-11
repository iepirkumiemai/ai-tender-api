from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ==========================================================
# STABILAIS A VARIANTS — BEZ AI, BEZ PARSERIEM, TIKAI JSON
# ==========================================================

app = FastAPI(
    title="AI Tender Analyzer — JSON Stable",
    version="0.1.0",
    description="Stabils JSON-only API karkass bez analīzes. Nekas nevar salūzt."
)

# CORS (WordPress / Frontend drošai piekļuvei)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# HEALTH CHECK
# ==========================================================
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "mode": "json-only",
        "message": "Serveris darbojas stabili."
    }

# ==========================================================
# GALVENAIS — JSON-ONLY FAILU IESNIEGŠANAS ENDPOINT
# ==========================================================
@app.post("/ai-tender/compare")
async def compare_files(
    requirements: UploadFile = File(...),
    candidate_docs: UploadFile = File(...)
):
    """
    A variants:
    - Saglabā abus failus
    - NEVEIC nekādu dokumentu analīzi
    - Atgriež JSON ar failu nosaukumiem
    """

    # Saglabā prasību failu
    req_path = Path(f"/tmp/{requirements.filename}")
    with open(req_path, "wb") as f:
        f.write(await requirements.read())

    # Saglabā kandidāta failu
    cand_path = Path(f"/tmp/{candidate_docs.filename}")
    with open(cand_path, "wb") as f:
        f.write(await candidate_docs.read())

    # Atgriež stabilu JSON atbildi
    return JSONResponse(
        content={
            "status": "ok",
            "requirements_file": req_path.name,
            "candidate_file": cand_path.name,
            "analysis": "A-variants darbojas. API saņem failus un atbild JSON formātā.",
            "note": "Šī nav reāla analīze – tā tiks pievienota B variantā."
        },
        indent=2
    )
