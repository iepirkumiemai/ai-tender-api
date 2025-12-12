import os
import zipfile
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="Tender Analyzer API", version="2.0")


# ============================================================
# DOCX FAILA NOLASĪŠANA — JAUNA, STABILA FUNKCIJA
# ============================================================

def extract_text_from_docx(path: str) -> str:
    """Robust DOCX extractor: works with ANY Word document."""
    try:
        text_blocks = []

        with zipfile.ZipFile(path) as z:
            xml_files = [
                f for f in z.namelist()
                if f.startswith("word/") and f.endswith(".xml")
            ]

            for xml_file in xml_files:
                try:
                    xml = z.read(xml_file).decode("utf-8", errors="ignore")

                    import re
                    cleaned = re.sub(r"<[^>]+>", " ", xml)
                    cleaned = cleaned.replace("\t", " ").replace("\n", " ").replace("\r", " ")
                    cleaned = " ".join(cleaned.split())

                    text_blocks.append(cleaned)
                except:
                    continue

        return "\n".join(text_blocks).strip()

    except Exception as e:
        return ""


# ============================================================
# ZIP FAILA NOLASĪŠANA
# ============================================================

def extract_texts_from_zip(path: str):
    candidates = {}

    with zipfile.ZipFile(path, "r") as zip_ref:
        for name in zip_ref.namelist():
            if name.lower().endswith(".txt"):
                txt = zip_ref.read(name).decode("utf-8", errors="ignore")
                candidates[name] = txt
            elif name.lower().endswith(".docx"):
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(zip_ref.read(name))
                    tmp.flush()
                    txt = extract_text_from_docx(tmp.name)
                    candidates[name] = txt

    return candidates


# ============================================================
# MAZIE APOF CIKLI, LAI NEPĀRSNIEGTU TOKEN LIMITUS
# ============================================================

def ai_compare(requirements: str, candidate: str):
    chunk_size = 8000
    chunks = [candidate[i:i + chunk_size] for i in range(0, len(candidate), chunk_size)]

    all_parts = []

    for chunk in chunks:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert evaluator for EU public procurement."},
                {"role": "user", "content":
                    f"Requirements:\n{requirements}\n\nCandidate submission:\n{chunk}\n\n"
                    "Evaluate this part. Provide KEY findings only."}
            ]
        )

        all_parts.append(response.choices[0].message.content)

    final = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Summarize compliance."},
            {"role": "user", "content": "\n\n".join(all_parts)}
        ]
    )

    return final.choices[0].message.content


# ============================================================
# API ENDPOINT /analyze
# ============================================================

@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    requirements_file: UploadFile = File(...),
    candidate_zip: UploadFile = File(...)
):

    # Temporary file for requirements
    with tempfile.NamedTemporaryFile(delete=False) as req_tmp:
        req_tmp.write(await requirements_file.read())
        req_tmp.flush()
        requirements_path = req_tmp.name

    requirements_text = extract_text_from_docx(requirements_path)

    if not requirements_text.strip():
        return "<h2>Requirements file unreadable or empty.</h2>"

    # Temporary file for ZIP
    with tempfile.NamedTemporaryFile(delete=False) as zip_tmp:
        zip_tmp.write(await candidate_zip.read())
        zip_tmp.flush()
        zip_path = zip_tmp.name

    candidates = extract_texts_from_zip(zip_path)

    if not candidates:
        return "<h2>ZIP archive contains no readable documents.</h2>"

    # Build HTML
    html = """
    <html><head>
    <style>
    body { font-family: Arial; padding: 20px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px; border: 1px solid #ccc; }
    th { background: #eee; }
    pre { white-space: pre-wrap; }
    </style>
    </head><body>
    <h2>Tender Analysis Result</h2>
    <table><tr><th>Candidate</th><th>Evaluation</th></tr>
    """

    for filename, text in candidates.items():
        result = ai_compare(requirements_text, text)
        html += f"<tr><td>{filename}</td><td><pre>{result}</pre></td></tr>"

    html += "</table></body></html>"

    return HTMLResponse(content=html)
