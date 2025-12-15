import os
import zipfile
import tempfile
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from docx import Document
from openai import OpenAI


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer – C Variant (INLINE HTML)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =======================
# HELPERS
# =======================

def extract_docx_text(path: str) -> str:
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except:
        return ""


def vision_extract_pdf(path: str) -> str:
    try:
        with open(path, "rb") as f:
            r = client.responses.create(
                model="gpt-4o",
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text",
                         "text": "Extract ALL text from this PDF. Preserve structure."},
                        {"type": "input_file",
                         "mime_type": "application/pdf",
                         "data": f.read()}
                    ]
                }],
                max_output_tokens=4096
            )
        return r.output_text or ""
    except:
        return ""


def extract_zip_files(path: str) -> List[str]:
    out = []
    with zipfile.ZipFile(path, "r") as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.write(z.read(name))
            tmp.close()
            out.append(tmp.name)
    return out


def classify_files(paths: List[str]) -> dict:
    r = {"text": [], "excel": [], "sign": []}
    for p in paths:
        l = p.lower()
        if l.endswith((".pdf", ".doc", ".docx")):
            r["text"].append(p)
        elif l.endswith((".xls", ".xlsx", ".csv")):
            r["excel"].append(p)
        elif l.endswith((".edoc", ".asice", ".p7s")):
            r["sign"].append(p)
    return r


# =======================
# GPT
# =======================

def ai_extract_requirements(text: str) -> str:
    r = client.responses.create(
        model="gpt-4o",
        input=f"Extract ALL requirements as JSON.\n{text}"
    )
    return r.output_text or ""


def ai_compare(req: str, cand: str) -> str:
    r = client.responses.create(
        model="gpt-4o",
        input=f"Compare requirements with candidate offer.\n\nRequirements:\n{req}\n\nOffer:\n{cand}"
    )
    return r.output_text or ""


def build_html(req: str, comp: str) -> str:
    return f"""
    <html><head><meta charset="utf-8"></head>
    <body>
    <h1>Tendera analīzes atskaite</h1>
    <h2>Prasības</h2>
    <pre>{req}</pre>
    <h2>Salīdzinājums</h2>
    <pre>{comp}</pre>
    </body></html>
    """


# =======================
# API
# =======================

@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    requirements: List[UploadFile] = File(...),
    candidates: List[UploadFile] = File(...)
):
    req_text = ""

    for f in requirements:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(await f.read())
        tmp.close()

        if f.filename.lower().endswith(".pdf"):
            req_text += vision_extract_pdf(tmp.name)
        else:
            req_text += extract_docx_text(tmp.name)

        os.unlink(tmp.name)

    if not req_text.strip():
        raise HTTPException(400, "Nav prasību teksta")

    req_struct = ai_extract_requirements(req_text)

    final = ""

    for f in candidates:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(await f.read())
        tmp.close()

        paths = extract_zip_files(tmp.name)
        cls = classify_files(paths)

        cand_text = ""

        for p in cls["text"]:
            cand_text += vision_extract_pdf(p) if p.endswith(".pdf") else extract_docx_text(p)

        if cls["excel"]:
            cand_text += "\nFinanšu pielikumi iesniegti."
        if cls["sign"]:
            cand_text += "\nPiedāvājums parakstīts."

        final += ai_compare(req_struct, cand_text)

        for p in paths:
            os.unlink(p)
        os.unlink(tmp.name)

    return HTMLResponse(build_html(req_struct, final))
