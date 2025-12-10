# main.py — Tender Engine v6.0 API Orchestrator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

from config import (
    ENGINE_NAME,
    VERSION,
    DEBUG_MODE,
    log
)

from downloader import download_multiple
from extractor_pdf import extract_pdf
from extractor_docx import extract_docx
from extractor_edoc import extract_edoc
from extractor_zip import extract_zip

from req_parser import extract_requirements
from candidate_parser import parse_multiple_candidates

from ai_compare import evaluate_candidate


# ============================================================
# FASTAPI INIT
# ============================================================

app = FastAPI(
    title=ENGINE_NAME,
    version=VERSION,
    description="AI Tender Requirement & Candidate Comparison Engine v6.0"
)


# ============================================================
# API REQUEST MODELS
# ============================================================

class CompareRequest(BaseModel):
    requirements: List[str]
    candidates: List[str]


# ============================================================
# HELPER — extract requirement documents
# ============================================================

def extract_requirement_docs(paths: list[str]) -> str:
    """
    Reads all requirement documents and concatenates text.
    Supports PDF, DOCX, EDOC, ZIP.
    """

    full_text = ""

    for path in paths:
        log(f"Extracting requirement file: {path}")
        if path.endswith(".pdf"):
            full_text += extract_pdf(path)
        elif path.endswith(".docx"):
            full_text += extract_docx(path)
        elif path.endswith(".edoc"):
            full_text += extract_edoc(path)
        elif path.endswith(".zip"):
            text, _ = extract_zip(path)
            full_text += text
        else:
            log(f"Unsupported requirement file: {path}")

    return full_text


# ============================================================
# /compare ENDPOINT
# ============================================================

@app.post("/compare")
async def compare_tender(req: CompareRequest):

    log("=== NEW /compare REQUEST RECEIVED ===")

    # ---------------------------------
    # Validate input
    # ---------------------------------
    if not req.requirements:
        raise HTTPException(status_code=400, detail="Missing requirement URLs.")

    if not req.candidates:
        raise HTTPException(status_code=400, detail="Missing candidate ZIP URLs.")

    # ---------------------------------
    # 1) Download requirement documents
    # ---------------------------------
    log("Downloading requirement documents...")
    requirement_paths = download_multiple(req.requirements)

    # ---------------------------------
    # 2) Extract requirement text
    # ---------------------------------
    log("Extracting requirements...")
    full_requirements_text = extract_requirement_docs(requirement_paths)

    if not full_requirements_text.strip():
        raise HTTPException(status_code=400, detail="No readable text in requirement documents.")

    # ---------------------------------
    # 3) Parse requirements into categories
    # ---------------------------------
    requirements_struct, requirements_debug = extract_requirements(full_requirements_text)

    # ---------------------------------
    # 4) Download + parse candidate ZIPs
    # ---------------------------------
    log("Parsing candidate ZIP archives...")
    candidates = parse_multiple_candidates(req.candidates)

    # ---------------------------------
    # 5) Compare each candidate with requirements
    # ---------------------------------
    results = []
    for candidate in candidates:
        log(f"Comparing candidate: {candidate['name']}")
        result = evaluate_candidate(requirements_struct, candidate)
        results.append(result)

    # ---------------------------------
    # 6) Build final API response
    # ---------------------------------
    response = {
        "status": "OK",
        "engine_version": VERSION,
        "requirements": requirements_struct,
        "requirement_debug": requirements_debug if DEBUG_MODE else None,
        "candidates": results
    }

    log("=== /compare COMPLETED SUCCESSFULLY ===")
    return response
