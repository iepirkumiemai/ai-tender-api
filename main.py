from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from typing import List
import tempfile
import os

app = FastAPI(
    title="AI Requirement vs Candidate Analyzer",
    version="1.0.0"
)

# ======================================================
# CORE ANALYSIS LOGIC (iekšā tajā pašā failā)
# ======================================================

def analyze_candidates(requirement_text: str, candidates: List[str]):
    results = []

    for idx, candidate_text in enumerate(candidates, start=1):
        # ŠEIT vēlāk var pieslēgt OpenAI
        # Pagaidām – deterministisks skeletons

        if len(candidate_text.strip()) < 50:
            status = "NOT_COMPLIANT"
            reason = "Insufficient information provided by candidate."
            manual_check = True
        else:
            status = "PARTIALLY_COMPLIANT"
            reason = "Some requirements appear to be addressed, but manual verification is required."
            manual_check = True

        results.append({
            "candidate_id": idx,
            "status": status,  # COMPLIANT | PARTIALLY_COMPLIANT | NOT_COMPLIANT
            "justification": reason,
            "manual_review_required": manual_check
        })

    return results


# ======================================================
# API ENDPOINT
# ======================================================

@app.post("/analyze")
async def analyze(
    requirement: UploadFile = File(...),
    candidates: List[UploadFile] = File(...)
):
    try:
        # Read requirement
        requirement_bytes = await requirement.read()
        requirement_text = requirement_bytes.decode("utf-8", errors="ignore")

        # Read candidates
        candidate_texts = []
        for c in candidates:
            content = await c.read()
            candidate_texts.append(content.decode("utf-8", errors="ignore"))

        analysis_result = analyze_candidates(
            requirement_text=requirement_text,
            candidates=candidate_texts
        )

        return JSONResponse({
            "requirement_file": requirement.filename,
            "total_candidates": len(candidate_texts),
            "results": analysis_result
        })

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ======================================================
# HEALTHCHECK
# ======================================================

@app.get("/health")
def health():
    return {"status": "ok"}
