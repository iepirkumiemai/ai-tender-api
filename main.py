import os
import zipfile
import tempfile
from typing import List, Dict, Any

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

from openai import OpenAI
import pdfminer.high_level
import mammoth


app = FastAPI(title="AI Tender Analyzer API", version="5.1")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ============================================================
# Utility: Split text into safe chunks (max 50k chars)
# ============================================================

def split_text_into_chunks(text: str, max_chars: int = 50000) -> List[str]:
    """
    Splits text into chunks of max_chars length.
    50k chars ≈ 25k tokens → safe for gpt-4.1 with 128k limit.
    """
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


# ============================================================
# Extractors
# ============================================================

def extract_pdf_text(file_path: str) -> str:
    try:
        return pdfminer.high_level.extract_text(file_path)
    except Exception:
        return ""


def extract_docx_text(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            result = mammoth.convert_to_html(f)
            html_text = result.value
            clean_text = html_text.replace("<p>", "\n").replace("</p>", "\n")
            return clean_text
    except Exception:
        return ""


def extract_edoc_text(file_path: str) -> Dict[str, Any]:
    """
    .edoc files = ZIP containers.
    Extract all files and return dictionary with extracted content.
    """
    edoc_output = {"xml_files": {}, "raw_files": {}}

    try:
        with zipfile.ZipFile(file_path, "r") as z:
            for name in z.namelist():
                try:
                    content = z.read(name)
                    if name.lower().endswith(".xml"):
                        try:
                            text = content.decode("utf-8", errors="ignore")
                            edoc_output["xml_files"][name] = text
                        except Exception:
                            pass
                    else:
                        edoc_output["raw_files"][name] = f"[binary data: {len(content)} bytes]"
                except Exception:
                    continue
    except Exception:
        pass

    return edoc_output


def extract_zip_contents(file_path: str) -> Dict[str, str]:
    """
    Extracts all files inside uploaded ZIP and reads text where possible.
    Returns dict: filename → extracted_text
    """
    extracted = {}

    try:
        with zipfile.ZipFile(file_path, "r") as z:
            for name in z.namelist():
                try:
                    temp_inner = z.extract(name, tempfile.gettempdir())
                    text = ""

                    if name.lower().endswith(".pdf"):
                        text = extract_pdf_text(temp_inner)

                    elif name.lower().endswith(".docx"):
                        text = extract_docx_text(temp_inner)

                    elif name.lower().endswith(".edoc"):
                        edoc_data = extract_edoc_text(temp_inner)
                        text = "\n".join(edoc_data.get("xml_files", {}).values())

                    else:
                        try:
                            with open(temp_inner, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except Exception:
                            text = ""

                    extracted[name] = text

                except Exception:
                    extracted[name] = ""
    except Exception:
        pass

    return extracted


# ============================================================
# AI Analysis
# ============================================================

def analyze_large_text(text: str) -> Dict[str, Any]:
    """
    Handles long documents by chunking into 50k character segments.
    Each chunk is individually analyzed by GPT-4.1
    """

    chunks = split_text_into_chunks(text, max_chars=50000)

    combined_results = {
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
                    {
                        "role": "system",
                        "content": "You are a tender evaluation assistant. Analyze the text chunk."
                    },
                    {
                        "role": "user",
                        "content": f"Analyze chunk {idx+1}:\n{chunk}"
                    }
                ],
            )

            result_text = response.output_text

            combined_results["summary"] += f"\n[Chunk {idx+1}] {result_text}"

            combined_results["compliance_score"] += 0.5
            combined_results["non_compliance_items"].append(f"Chunk {idx+1}: (auto placeholder)")
            combined_results["recommendations"].append(f"Review chunk {idx+1} for improvements.")

        except Exception as e:
            combined_results["summary"] += f"\n[Chunk {idx+1}] ERROR: {str(e)}"

    if chunks:
        combined_results["compliance_score"] = round(
            combined_results["compliance_score"] / len(chunks), 3
        )

    return combined_results


# ============================================================
# Main /upload Endpoint
# ============================================================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        suffix = os.path.splitext(file.filename)[1]
        temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(temp_fd)

        with open(temp_path, "wb") as f:
            f.write(await file.read())

        # Determine file type
        if suffix.lower() == ".pdf":
            extracted_text = extract_pdf_text(temp_path)

        elif suffix.lower() == ".docx":
            extracted_text = extract_docx_text(temp_path)

        elif suffix.lower() == ".edoc":
            edoc_info = extract_edoc_text(temp_path)
            extracted_text = "\n".join(edoc_info.get("xml_files", {}).values())

        elif suffix.lower() == ".zip":
            zip_data = extract_zip_contents(temp_path)
            extracted_text = "\n".join(zip_data.values())

        else:
            extracted_text = "Unsupported file format"

        # Perform AI analysis
        ai_output = analyze_large_text(extracted_text)

        return JSONResponse({
            "status": "OK",
            "filename": file.filename,
            "file_type": suffix.lower(),
            "extracted_text_length": len(extracted_text),
            "ai_analysis": ai_output
        })

    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)
