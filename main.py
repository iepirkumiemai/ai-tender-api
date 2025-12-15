import os
import io
import zipfile
import tempfile
from typing import List

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from openai import OpenAI

# =========================
# CONFIG
# =========================

OPENAI_MODEL = "gpt-4.1-mini"
MAX_AI_BYTES = 300_000  # drošs konteksta limits (~300 KB)

client = OpenAI()

# =========================
# FASTAPI APP
# =========================

app = FastAPI(title="Tender Analyzer API (C variant)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# AI EXTRACTION
# =========================

def ai_extract_from_binary(filename: str, data: bytes) -> str:
    """
    Single AI extraction call (expects SMALL input).
    """
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            f"You are an expert in public procurement analysis.\n"
                            f"Extract meaningful textual content from this file.\n"
                            f"Filename: {filename}\n"
                            f"Return plain text only."
                        ),
                    },
                    {
                        "type": "input_file",
                        "filename": filename,
                        "file": data,
                    },
                ],
            }
        ],
    )

    return response.output_text or ""


def safe_ai_extract(filename: str, data: bytes) -> str:
    """
    SAFE AI extraction with automatic chunking.
    """
    if not data:
        return ""

    if len(data) <= MAX_AI_BYTES:
        return ai_extract_from_binary(filename, data)

    text = ""
    part = 1
    for i in range(0, len(data), MAX_AI_BYTES):
        chunk = data[i : i + MAX_AI_BYTES]
        text += ai_extract_from_binary(
            f"{filename} [part {part}]",
            chunk
        )
        text += "\n"
        part += 1

    return text


# =========================
# ZIP HANDLING
# =========================

def extract_zip_recursive(zip_bytes: bytes) -> List[tuple]:
    """
    Returns list of (filename, bytes) from ZIP, recursively.
    """
    extracted = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue

            data = z.read(name)

            if name.lower().endswith(".zip"):
                extracted.extend(extract_zip_recursive(data))
            else:
                extracted.append((name, data))

    return extracted


# =========================
# ANALYSIS LOGIC
# =========================

def analyze_candidate_documents(files: List[tuple]) -> str:
    """
    Extracts all texts from candidate files.
    """
    combined_text = ""

    for filename, data in files:
        combined_text += f"\n\n=== FILE: {filename} ===\n"
        combined_text += safe_ai_extract(filename, data)

    return combined_text


def build_html_report(requirements_text: str, candidate_text: str) -> str:
    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Tendera analīzes atskaite</title>
    </head>
    <body>
        <h1>Tendera analīzes atskaite</h1>

        <h2>Prasības</h2>
        <pre>{requirements_text}</pre>

        <h2>Kandidāta piedāvājuma saturs</h2>
        <pre>{candidate_text}</pre>
    </body>
    </html>
    """


# =========================
# API ENDPOINT
# =========================

@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    requirements: UploadFile = File(...),
    offer: UploadFile = File(...)
):
    try:
        # --- read requirement document ---
        req_bytes = await requirements.read()
        requirements_text = safe_ai_extract(requirements.filename, req_bytes)

        # --- read offer ZIP ---
        offer_bytes = await offer.read()

        if not offer.filename.lower().endswith(".zip"):
            return JSONResponse(
                status_code=400,
                content={"error": "Offer must be a ZIP container"},
            )

        extracted_files = extract_zip_recursive(offer_bytes)

        candidate_text = analyze_candidate_documents(extracted_files)

        html = build_html_report(requirements_text, candidate_text)
        return HTMLResponse(content=html)

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )
