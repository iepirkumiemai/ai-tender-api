import os
import zipfile
import tempfile
import shutil
from typing import List, Dict

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from openai import OpenAI
from docx import Document


# =========================================================
# APP INIT
# =========================================================
app = FastAPI(title="AI Iepirkumu Analīzes API")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing")

client = OpenAI(api_key=OPENAI_API_KEY)


# =========================================================
# PALĪGFUNKCIJAS
# =========================================================
def extract_docx_text(file_path: str) -> str:
    doc = Document(file_path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_edoc_text(edoc_path: str) -> str:
    """
    EDOC = ZIP ar parakstītiem dokumentiem.
    Šeit mēs izvelkam VISUS iekšā esošos DOCX/PDF/DOCX tekstus.
    (šobrīd – DOCX kā drošs minimums)
    """
    extracted_texts = []

    with zipfile.ZipFile(edoc_path, "r") as z:
        with tempfile.TemporaryDirectory() as tmp:
            z.extractall(tmp)
            for root, _, files in os.walk(tmp):
                for f in files:
                    if f.lower().endswith(".docx"):
                        extracted_texts.append(
                            extract_docx_text(os.path.join(root, f))
                        )

    return "\n".join(extracted_texts)


def extract_candidate_text(file_path: str) -> str:
    if file_path.lower().endswith(".docx"):
        return extract_docx_text(file_path)

    if file_path.lower().endswith(".edoc"):
        return extract_edoc_text(file_path)

    return ""


# =========================================================
# AI ANALĪZE
# =========================================================
def analyze_candidate(requirements_text: str, candidate_text: str) -> Dict:
    prompt = f"""
Tu esi publisko iepirkumu komisijas eksperts.

PRASĪBAS:
----------------
{requirements_text}

KANDIDĀTA DOKUMENTI:
----------------
{candidate_text}

Uzdevums:
1. Novērtē, vai kandidāts atbilst prasībām.
2. Klasificē:
   - COMPLIANT
   - PARTIALLY_COMPLIANT
   - NON_COMPLIANT
3. Ja ir neskaidrības, atzīmē manuālas pārbaudes nepieciešamību.
4. Ja neatbilst – sniedz īsu pamatojumu.

Atgriez TIKAI šo JSON struktūru:

{{
  "status": "COMPLIANT | PARTIALLY_COMPLIANT | NON_COMPLIANT",
  "justification": "...",
  "manual_review_required": true | false
}}
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    import json
    return json.loads(response.choices[0].message.content)


# =========================================================
# ENDPOINT
# =========================================================
@app.post("/analyze")
async def analyze(
    requirement: UploadFile = File(...),
    candidates: UploadFile = File(...)
):
    try:
        with tempfile.TemporaryDirectory() as tmp:
            # --- Saglabā prasības
            req_path = os.path.join(tmp, requirement.filename)
            with open(req_path, "wb") as f:
                f.write(await requirement.read())

            requirements_text = extract_docx_text(req_path)

            # --- Kandidāti (ZIP)
            cand_zip_path = os.path.join(tmp, candidates.filename)
            with open(cand_zip_path, "wb") as f:
                f.write(await candidates.read())

            results = []
            candidate_id = 1

            with zipfile.ZipFile(cand_zip_path, "r") as z:
                z.extractall(tmp)

            for root, _, files in os.walk(tmp):
                for file in files:
                    if file.lower().endswith((".docx", ".edoc")):
                        cand_path = os.path.join(root, file)
                        cand_text = extract_candidate_text(cand_path)

                        if not cand_text.strip():
                            continue

                        analysis = analyze_candidate(
                            requirements_text,
                            cand_text
                        )

                        results.append({
                            "candidate_id": candidate_id,
                            "file": file,
                            **analysis
                        })
                        candidate_id += 1

            return JSONResponse({
                "requirement_file": requirement.filename,
                "total_candidates": len(results),
                "results": results
            })

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )
