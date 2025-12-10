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

app = FastAPI(title="AI Tender Compliance Engine", version="5.4")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ============================================================
# SAFE LIMITS
# ============================================================

MAX_ZIP_SIZE_MB = 40
MAX_ZIP_FILES = 30
MAX_TEXT_SIZE = 300_000
CHUNK_SIZE = 50_000


# ============================================================
# TIMEOUT HANDLER
# ============================================================

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Timeout exceeded")

signal.signal(signal.SIGALRM, timeout_handler)


# ============================================================
# UTILS
# ============================================================

def debug(msg: str):
    print(f"[DEBUG] {msg}", flush=True)


# ============================================================
# CHUNKING
# ============================================================

def split_text_into_chunks(text: str, max_chars: int = CHUNK_SIZE) -> List[str]:
    chunks = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
    debug(f"Split text into {len(chunks)} chunks.")
    return chunks


# ============================================================
# FILE EXTRACTORS
# ============================================================

def extract_pdf(path: str) -> str:
    try:
        debug(f"Extracting PDF: {path}")
        return pdfminer.high_level.extract_text(path)
    except Exception as e:
        debug(f"PDF extraction failed: {e}")
        return ""


def extract_docx(path: str) -> str:
    try:
        debug(f"Extracting DOCX: {path}")
        with open(path, "rb") as f:
            html = mammoth.convert_to_html(f).value
            return html.replace("<p>", "\n").replace("</p>", "\n")
    except Exception as e:
        debug(f"DOCX extraction failed: {e}")
        return ""


def extract_edoc(path: str) -> str:
    out = []
    debug(f"Extracting EDOC: {path}")
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                try:
                    content = z.read(name)
                    if name.lower().endswith(".xml"):
                        out.append(content.decode("utf-8", errors="ignore"))
                except Exception as e:
                    debug(f"EDOC internal error on {name}: {e}")
                    continue
    except Exception as e:
        debug(f"EDOC extraction failed: {e}")
        return ""
    return "\n".join(out)


def safe_extract_zip(path: str) -> str:
    final_text = []
    total_size = 0

    debug(f"Extracting ZIP file: {path}")

    try:
        with zipfile.ZipFile(path, "r") as z:
            names = z.namelist()
            debug(f"ZIP contains {len(names)} files.")

            if len(names) > MAX_ZIP_FILES:
                debug("ZIP exceeds SAFE file count limit.")
                return ""

            for name in names:
                debug(f"Extracting file: {name}")

                # Timeout for safety
                signal.alarm(2)
                try:
                    extracted = z.extract(name, tempfile.gettempdir())
                except Exception as e:
                    debug(f"Failed to extract {name}: {e}")
                    continue
                finally:
                    signal.alarm(0)

                ext = name.lower()
                text = ""

                try:
                    if ext.endswith(".pdf"):
                        text = extract_pdf(extracted)
                    elif ext.endswith(".docx"):
                        text = extract_docx(extracted)
                    elif ext.endswith(".edoc"):
                        text = extract_edoc(extracted)
                    else:
                        try:
                            with open(extracted, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except:
                            text = ""
                except Exception as e:
                    debug(f"Extraction error for {name}: {e}")
                    text = ""

                total_size += len(text)
                if total_size > MAX_TEXT_SIZE:
                    debug("Reached MAX_TEXT_SIZE limit; trimming.")
                    final_text.append(text[:50000])
                    break

                final_text.append(text)

    except Exception as e:
        debug(f"ZIP extraction failed: {e}")
        return ""

    debug(f"Final extracted ZIP text length: {len(''.join(final_text))}")
    return "\n".join(final_text)


# ============================================================
# GPT-4.1 CHUNK ANALYSIS (SUPER CONSERVATIVE)
# ============================================================

def analyze_chunk(chunk: str, index: int) -> Dict[str, Any]:

    debug(f"Analyzing chunk {index} ({len(chunk)} chars)")

    prompt = [
        {
            "role": "system",
            "content": (
                "You are a tender compliance auditor. "
                "Your job is to evaluate text EXACTLY and CONSERVATIVELY. "
                "Rules:\n"
                "- GREEN only if text 100% clearly and explicitly satisfies requirements.\n"
                "- If ANY uncertainty → YELLOW.\n"
                "- If requirement is missing or contradicts → RED.\n"
                "Always return structured compliance analysis."
            )
        },
        {
            "role": "user",
            "content": f"Analyze this text chunk:\n\n{chunk}"
        }
    ]

    try:
        response = client.responses.create(
            model="gpt-4.1",
            input=prompt,
        )

        output = response.output_text
        debug(f"AI raw output for chunk {index}:\n{output[:500]}...\n")

        #
        # Now classify using a second ultra-short system to ensure structure:
        #
        audit_prompt = [
            {
                "role": "system",
                "content": (
                    "Classify compliance from model output.\n"
                    "Rules:\n"
                    "- If fully compliant and explicit → GREEN.\n"
                    "- If unclear or partial → YELLOW.\n"
                    "- If missing or contradictory → RED.\n"
                    "Respond ONLY in JSON with fields:\n"
                    "{\n"
                    "  'status': 'green/yellow/red',\n"
                    "  'reason': {\n"
                    "       'issue': '...',\n"
                    "       'risk': '...',\n"
                    "       'note': '...'\n"
                    "  }\n"
                    "}"
                )
            },
            {
                "role": "user",
                "content": output
            }
        ]

        confirm = client.responses.create(
            model="gpt-4.1",
            input=audit_prompt
        )

        final_json = confirm.output_text
        debug(f"AI structured JSON chunk {index}:\n{final_json}\n")

        # Parse output safely
        import json
        parsed = json.loads(final_json)

        status = parsed.get("status", "yellow")
        reason = parsed.get("reason", {})

        # Add icon
        icon = "🟢" if status == "green" else ("🟡" if status == "yellow" else "🔴")

        return {
            "id": index,
            "status": status,
            "icon": icon,
            "reason": {
                "issue": reason.get("issue", ""),
                "risk": reason.get("risk", ""),
                "note": reason.get("note", "")
            }
        }

    except Exception as e:
        debug(f"AI analysis failed on chunk {index}: {e}")
        return {
            "id": index,
            "status": "yellow",
            "icon": "🟡",
            "reason": {
                "issue": "AI processing error",
                "risk": "Chunk could not be fully evaluated",
                "note": str(e)
            }
        }


# ============================================================
# HIGH-LEVEL ANALYSIS (COMBINING ALL CHUNKS)
# ============================================================

def combine_chunk_results(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:

    statuses = [c["status"] for c in chunks]
    green_count = statuses.count("green")
    yellow_count = statuses.count("yellow")
    red_count = statuses.count("red")

    debug(f"Chunk status summary: GREEN={green_count}, YELLOW={yellow_count}, RED={red_count}")

    # Super conservative logic
    if red_count > 0:
        result = "red"
        icon = "🔴"
        final_note = "One or more chunks contain clear non-compliance."
    elif yellow_count > 0:
        result = "yellow"
        icon = "🟡"
        final_note = "One or more chunks are unclear and require manual verification."
    else:
        result = "green"
        icon = "🟢"
        final_note = "All chunks fully satisfy requirements."

    # Confidence = GREEN / ALL
    confidence = round(green_count / max(1, len(chunks)), 3)

    # Build structured summary (GPT-4.1)
    summary_prompt = [
        {
            "role": "system",
            "content": (
                "Summarize tender compliance based on chunk classification. "
                "Provide four structured sections: overview, strengths, risks, unclear."
            )
        },
        {
            "role": "user",
            "content": f"Chunk results: {chunks}"
        }
    ]

    try:
        summary_resp = client.responses.create(
            model="gpt-4.1",
            input=summary_prompt
        )

        summary_text = summary_resp.output_text
        debug(f"AI summary output:\n{summary_text}\n")

        import json
        summary = json.loads(summary_text)

    except Exception as e:
        debug(f"Summary generation error: {e}")
        summary = {
            "overview": "",
            "strengths": [],
            "risks": [],
            "unclear": []
        }

    return {
        "result": result,
        "icon": icon,
        "confidence": confidence,
        "summary": summary,
        "final_reason": final_note
    }


# ============================================================
# API ENDPOINT
# ============================================================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    filename = file.filename
    suffix = os.path.splitext(filename)[1].lower()

    debug(f"Uploaded file: {filename}")

    size_mb = len(await file.read()) / (1024 * 1024)
    await file.seek(0)

    debug(f"File size: {size_mb:.2f} MB")

    if size_mb > MAX_ZIP_SIZE_MB:
        debug("Rejected: ZIP exceeds size limit.")
        return JSONResponse({"error": "ZIP too large"}, status_code=400)

    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)

    with open(temp_path, "wb") as f:
        f.write(await file.read())

    # Extract text
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

    debug(f"Extracted text length: {len(text)}")

    if len(text) > MAX_TEXT_SIZE:
        debug("Text trimmed to MAX_TEXT_SIZE.")
        text = text[:MAX_TEXT_SIZE]

    # Chunking
    chunks = split_text_into_chunks(text)

    # Analyze chunks
    chunk_results = []
    for i, chunk in enumerate(chunks):
        result = analyze_chunk(chunk, i + 1)
        chunk_results.append(result)

    # Combine results
    final = combine_chunk_results(chunk_results)

    response = {
        "status": "OK",
        "filename": filename,
        "file_type": suffix,
        "result": final["result"],
        "icon": final["icon"],
        "confidence": final["confidence"],
        "summary": final["summary"],
        "final_reason": final["final_reason"],
        "chunks": chunk_results
    }

    debug("FINAL RESULT:")
    debug(str(response))

    return JSONResponse(response)
