import os
import zipfile
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="AI Tender Analyzer", version="1.0")

# ===========================================================
# Palīgfunkcija – lasa PDF, DOCX, TXT kā tekstu
# ===========================================================
import docx
from PyPDF2 import PdfReader

def extract_text_from_file(path: str) -> str:
    ext = path.lower()

    if ext.endswith(".txt"):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if ext.endswith(".docx"):
        doc = docx.Document(path)
        return "\n".join([p.text for p in doc.paragraphs])

    if ext.endswith(".pdf"):
        reader = PdfReader(path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text

    return ""


# ===========================================================
# AI analīze (latviešu valodā)
# ===========================================================
def analyze_document(requirements_text: str, candidate_text: str) -> str:
    prompt = f"""
Tu esi publisko iepirkumu eksperts Latvijā ar 15 gadu pieredzi.
Salīdzini iesniegto kandidāta dokumentu ar prasību dokumentu.

ATBILDI TIKAI LATVIEŠU VALODĀ.

Struktūra:

1) **Kopsavilkums** – 5–7 teikumi.
2) **Stiprās puses** – punkti.
3) **Vājās puses** – punkti.
4) **Atbilstības risks** – Zems / Vidējs / Augsts + pamatojums.
5) **Gala vērtējums** – Atbilst / Daļēji atbilst / Neatbilst.

Prasību dokuments:
-------------------
{requirements_text}

Kandidāta dokuments:
---------------------
{candidate_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Tu esi publisko iepirkumu eksperts."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=5000,
        temperature=0.2,
    )

    return response.choices[0].message.content


# ===========================================================
# API: /analyze
# ===========================================================
@app.post("/analyze")
async def analyze(
    requirements: UploadFile = File(...),
    candidates_zip: UploadFile = File(...)
):
    # 1. Nolasām prasību dokumentu
    with tempfile.NamedTemporaryFile(delete=False) as tmp_req:
        tmp_req.write(await requirements.read())
        tmp_req_path = tmp_req.name

    requirements_text = extract_text_from_file(tmp_req_path)

    # 2. Atveram ZIP ar kandidātu dokumentiem
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "candidates.zip")
        with open(zip_path, "wb") as f:
            f.write(await candidates_zip.read())

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmpdir)

        results_html = """
        <html><head>
        <style>
        body { font-family: Arial; padding: 20px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; border: 1px solid #ccc; vertical-align: top; }
        th { background: #f0f0f0; }
        pre { white-space: pre-wrap; font-family: Arial; }
        </style>
        </head><body>
        <h2>Iepirkuma kandidātu analīzes rezultāti</h2>
        <table>
        <tr><th>Dokuments</th><th>Analīze</th></tr>
        """

        # 3. Apstrādājam katru failu ZIP iekšā
        for root, _, files in os.walk(tmpdir):
            for filename in files:
                if filename.endswith((".pdf", ".docx", ".txt")):
                    full_path = os.path.join(root, filename)
                    candidate_text = extract_text_from_file(full_path)

                    if len(candidate_text.strip()) < 20:
                        analysis = "(Nevarēja nolasīt tekstu – iespējams skenēts PDF.)"
                    else:
                        analysis = analyze_document(requirements_text, candidate_text)

                    results_html += f"""
                    <tr>
                        <td>{filename}</td>
                        <td><pre>{analysis}</pre></td>
                    </tr>
                    """

        results_html += "</table></body></html>"

    return HTMLResponse(content=results_html)
