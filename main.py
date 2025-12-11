# ============================
# AI Tender Comparison Engine
# Full working main.py
# ============================

import os
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

# --------------------------------------
# Fake comparison function (works now)
# --------------------------------------
def compare_files(requirement_docs, candidate_docs):
    """
    Temporary comparison function.
    Returns simple HTML showing uploaded filenames.
    """
    html = "<h1>Comparison Report</h1>"
    html += "<h2>Requirements:</h2><ul>"
    for f in requirement_docs:
        html += f"<li>{f.filename}</li>"
    html += "</ul>"

    html += "<h2>Candidates:</h2><ul>"
    for f in candidate_docs:
        html += f"<li>{f.filename}</li>"
    html += "</ul>"

    html += "<p>Status: OK — Engine is working.</p>"
    return html


# =====================================================
# FastAPI init
# =====================================================
app = FastAPI(
    title="AI Tender Comparison Engine",
    version="13.0"
)

app.add_middleware(
    CORSMMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================
# Root endpoint
# =====================================================
@app.get("/")
async def root():
    return {"message": "AI Tender Comparison Engine is running."}


# =====================================================
# MAIN HTML COMPARISON ENDPOINT
# =====================================================
@app.post("/compare_files_html", response_class=HTMLResponse)
async def compare_files_html(
    requirements: list[UploadFile] = File(...),
    candidates: list[UploadFile] = File(...)
):
    html_content = compare_files(requirements, candidates)
    return HTMLResponse(content=html_content, status_code=200)

