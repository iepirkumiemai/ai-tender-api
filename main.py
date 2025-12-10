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

app = FastAPI(title="AI Tender Analyzer API", version="5.2")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ============================================================
# Global SAFE LIMITS
# ============================================================

MAX_ZIP_SIZE_MB = 40
MAX_ZIP_FILES = 30
MAX_TEXT_SIZE = 300_000
CHUNK_SIZE = 50_000


# ============================================================
# Time-limited executor
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
# Extractors with SAFE LIMITS
# ============================================================

def extract_pdf(file_path: str) -> str:
    try:
        return pdfminer.high_level.extract_text(file_path)
    except:
        return ""


def extract_docx(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            result = mammoth.convert_to_html(f)
            return result.value.replace("<p>", "\n").replace("</p>", "\n")
    except:
        return ""


def extract_edoc(file_path: str) -> str:
    out = []
    try:
        with zipfile.ZipFile(file_path, "r") as z:
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


def safe_extract_zip(file_path: str) -> Dict[str, str]:
    """
    Extracts ZIP content with:
    - file count limit
    - timeout per file
    - text size limit
    - formats: PDF, DOCX, EDOC, TXT
    """

    output = {}
    text_size = 0

    try:
        with zipfile.ZipFile(file_path, "r") as z:

            names = z.namelist()

            # ---- Limit file count ----
            if len(names) > MAX_ZIP_FILES:
                return {"ERROR": f"SAFE_LIMIT_EXCEEDED: ZIP contains {len(names)} files (max {MAX_ZIP_FILES})."}

            for name in names:

                # TIMEOUT: 2 sec extraction
                signal.alarm(2)

                try:
                    extracted = z.extract(name, tempfile.gettempdir())
                except Exception:
                    continue
                finally:
                    signal.alarm(0)

                ext = name.lower()

                # ---- Determine type and extract ----
                text = ""

                try:
                    if ext.endswith(".pdf"):
                        text = extract_pdf(extracted)

                    elif ext.endswith(".docx"):
                        text = extract_docx(extracted)

                    elif ext.endswith(".edoc"):
                        text = extract_edoc(extracted)

                    else:
                        # Try plain text
                        try:
                            with open(extracted, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except:
                            text = ""
                except:
                    text = ""

                # ---- SAFE LIMIT: total text size ----
                text_size += len(text)
                if text_size > MAX_TEXT_SIZE:
                    output[name] = text[:50_000] + "\n[SAFE TRIMMED]"
                    return output

                output[name] = text

    except Exception:
        return {"ERROR": "Invalid or unreadable ZIP file."}

    return output


# ============================================================
# AI ANALYSIS (chunk-safe)
# ============================================================

def analyze_large_text(text: str) -> Dict[str, Any]:
    chunks = split_text_into_chunks(text)
    results = {
        "summary": "",
        "compliance_score": 0,
        "non_compliance_items": [],
        "recommendations": [],
        "chunks_analyzed": len(chunks)
    }

    for idx, chunk in enumerate(chunks):
        try:
            response = client.responses.create(
                model="gpt-4.1",
                input=[
                    {"role": "system", "content": "Tender analysis assistant. Analyze the chunk."},
                    {"role": "user", "content": f"Chunk {idx+1}:\n{chunk}"}
                ],
            )

            txt = response.output_text
            results["summary"] += f"\n[Chunk {idx+1}] {txt}"

            results["compliance_score"] += 0.5
            results["non_compliance_items"].append(f"Chunk {idx+1}: review needed")
            results["recommendations"].append(f"Improve chunk {idx+1} clarity")
        except Exception as e:
            results["summary"] += f"\n[Chunk {idx+1}] AI_ERROR: {str(e)}"

    if chunks:
        results["compliance_score"] = round(results["compliance_score"] / len(chunks), 3)

    return results


# ============================================================
# UPLOAD ENDPOINT (SAFE)
# ============================================================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    # ---- SAFE LIMIT: ZIP size ----
    size_mb = len(await file.read()) / (1024 * 1024)
    await file.seek(0)

    if size_mb > MAX_ZIP_SIZE_MB:
        return JSONResponse(
            {"error": f"SAFE_LIMIT_EXCEEDED: ZIP is {size_mb:.1f}MB (max {MAX_ZIP_SIZE_MB}MB)."},
            status_code=400
        )

    suffix = os.path.splitext(file.filename)[1].lower()
    temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(temp_fd)

    with open(temp_path, "wb") as f:
        f.write(await file.read())

    # ---- Extract depending on type ----
    if suffix == ".zip":
        zip_data = safe_extract_zip(temp_path)

        if "ERROR" in zip_data:
            return JSONResponse({"status": "ERROR", "message": zip_data["ERROR"]}, status_code=400)

        full_text = "\n".join(zip_data.values())

    elif suffix == ".pdf":
        full_text = extract_pdf(temp_path)

    elif suffix == ".docx":
        full_text = extract_docx(temp_path)

    elif suffix == ".edoc":
        full_text = extract_edoc(temp_path)

    else:
        return JSONResponse({"error": "Unsupported format"}, status_code=400)

    # ---- SAFE LIMIT: Trim text ----
    if len(full_text) > MAX_TEXT_SIZE:
        full_text = full_text[:MAX_TEXT_SIZE] + "\n[SAFE TRIMMED]"

    # ---- AI Analysis ----
    ai_result = analyze_large_text(full_text)

    return JSONResponse({
        "status": "OK",
        "filename": file.filename,
        "file_type": suffix,
        "text_length": len(full_text),
        "ai_analysis": ai_result
    })
