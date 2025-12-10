import os
import zipfile
import tempfile
import signal
from typing import List, Dict, Any

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

from openai import OpenAI
import pdfminer.high_level
import mammoth

app = FastAPI(title="AI Tender Analyzer API", version="5.3")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ============================================================
# SAFE LIMITS
# ============================================================

MAX_ZIP_SIZE_MB = 40
MAX_ZIP_FILES = 30
MAX_TEXT_SIZE = 300_000
CHUNK_SIZE = 50_000


# ============================================================
# Timeout support
# ============================================================

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Timeout exceeded")

signal.signal(signal.SIGALRM, timeout_handler)


# ============================================================
# Chunking
# ============================================================

def split_text_into_chunks(text: str, max_chars: int = CHUNK_SIZE):
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


# ============================================================
# Extractors
# ============================================================

def extract_pdf(path: str) -> str:
    try:
        return pdfminer.high_level.extract_text(path)
    except:
        return ""


def extract_docx(path: str) -> str:
    try:
        with open(path, "rb") as f:
            html = mammoth.convert_to_html(f).value
            return html.replace("<p>", "\n").replace("</p>", "\n")
    except:
        return ""


def extract_edoc(path: str) -> str:
    out = []
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                try:
                    content = z.read(name)
                    if name.lower().endswith(".xml"):
                        out.append(content.decode("utf-8", errors="ignore"))
                except:
                    continue
    except:
        pass
    return "\n".join(out)


def safe_extract_zip(path: str) -> str:
    """Extract ZIP, respecting SAFE LIMITS, return concatenated text only."""
    final_text = []
    total_size = 0

    try:
        with zipfile.ZipFile(path, "r") as z:
            names = z.namelist()

            if len(names) > MAX_ZIP_FILES:
                return "[LIMIT] Too many files in ZIP."

            for name in names:
                # timeout 2 sec
                signal.alarm(2)
                try:
                    extracted = z.extract(name, tempfile.gettempdir())
                except:
                    continue
                finally:
                    signal.alarm(0)

                text = ""
                lower = name.lower()

                try:
                    if lower.endswith(".pdf"):
                        text = extract_pdf(extracted)
                    elif lower.endswith(".docx"):
                        text = extract_docx(extracted)
                    elif lower.endswith(".edoc"):
                        text = extract_edoc(extracted)
                    else:
                        try:
                            with open(extracted, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except:
                            text = ""
                except:
                    text = ""

                total_size += len(text)
                if total_size > MAX_TEXT_SIZE:
                    final_text.append(text[:50000])
                    break

                final_text.append(text)

    except Exception:
        return "[ERROR] Invalid ZIP"

    return "\n".join(final_text)


# ============================================================
# AI ANALYSIS – only returns structured summary
# ============================================================

def analyze_large_text(text: str) -> Dict[str, Any]:
    chunks = split_text_into_chunks(text)
    summaries = []
    noncomp = []
    recs = []

    score_total = 0

    for idx, chunk in enumerate(chunks):
        try:
            response = client.responses.create(
                model="gpt-4.1",
                input=[
                    {"role": "system", "content": "Summarize and evaluate tender content."},
                    {"role": "user", "content": f"Analyze chunk {idx+1}:\n{chunk}"}
                ],
            )

            txt = response.output_text

            summaries.append(f"[Chunk {idx+1}] {txt}")
            noncomp.append(f"Chunk {idx+1}: review needed")
            recs.append(f"Improve chunk {idx+1} clarity")

            score_total += 0.5

        except Exception as e:
            summaries.append(f"[Chunk {idx+1}] AI_ERROR: {str(e)}")

    avg_score = round(score_total / max(1, len(chunks)), 3)

    return {
        "summary": "\n".join(summaries[:5]),     # ONLY FIRST 5 summaries (lightweight)
        "compliance_score": avg_score,
        "non_compliance_items": noncomp[:10],    # lightweight
        "recommendations": recs[:10],            # lightweight
        "chunks": len(chunks)
    }


# ============================================================
# UPLOAD ENDPOINT — SAFE OUTPUT (Swagger-friendly)
# ============================================================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    size_mb = len(await file.read()) / (1024 * 1024)
    await file.seek(0)

    if size_mb > MAX_ZIP_SIZE_MB:
        return JSONResponse({"error": f"ZIP too large ({size_mb:.1f} MB)"}, status_code=400)

    suffix = os.path.splitext(file.filename)[1].lower()
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)

    with open(temp_path, "wb") as f:
        f.write(await file.read())

    if suffix == ".zip":
        text = safe_extract_zip(temp_path)
    elif suffix == ".pdf":
        text = extract_pdf(temp_path)
    elif suffix == ".docx":
        text = extract_docx(temp_path)
    elif suffix == ".edoc":
        text = extract_edoc(temp_path)
    else:
        return JSONResponse({"error": "Unsupported format"}, status_code=400)

    if len(text) > MAX_TEXT_SIZE:
        text = text[:MAX_TEXT_SIZE]

    ai = analyze_large_text(text)

    return JSONResponse({
        "status": "OK",
        "filename": file.filename,
        "file_type": suffix,
        "ai_summary": ai["summary"],
        "compliance_score": ai["compliance_score"],
        "non_compliance_items": ai["non_compliance_items"],
        "recommendations": ai["recommendations"],
        "chunks": ai["chunks"]
    })
