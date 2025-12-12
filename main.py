import os
import zipfile
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from openai import OpenAI
from PyPDF2 import PdfReader

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()


# ==============================
# 1) Būvējam drošu DOCX parseri Railway videi
# ==============================
def extract_text_from_docx(path: str) -> str:
    """Extract text from DOCX using built-in ZIP + XML parsing (Railway-safe)."""
    try:
        with zipfile.ZipFile(path) as docx:
            xml = docx.read("word/document.xml").decode("utf-8", errors="ignore")

        # Pamatapstrāde
        xml = xml.replace("</w:p>", "\n").replace("<w:t>", "").replace("</w:t>", "")

        import re
        text = re.sub(r"<[^>]+>", "", xml)

        return text.strip()
    except:
        return ""


# ==============================
# 2) PDF parseris
# ==============================
def extract_text_from_pdf(path: str) -> str:
    try:
        reader = PdfReader(path)
        text = ""
        for page in reader.pages:
            txt = page.extract_text() or ""
            text += txt + "\n"
        return text.strip()
    except:
        return ""


# ==============================
# 3) TXT parseris
# ==============================
def extract_text_from_txt(path: str) -> str:
    try:
        return open(path, "r", encoding="utf-8", errors="ignore").read()
    except:
        return ""


# ==============================
# 4) Universālais parseris
# ==============================
def extract_text_from_file(path: str) -> str:
    name = path.lower()

    if name.endswith(".docx"):
        return extract_text_from_docx(path)

    if name.endswith(".pdf"):
        return extract_text_from_pdf(path)

    if name.endswith(".txt"):
        return extract_text_from_txt(path)

    return ""


# ==============================
# 5) GPT-4o tendera analīze (droša, ar token limitu)
# ==============================
def ai_analyze(requirements: str, candidate: str) -> str:

    max_chunk = 7000  # Droši GPT-4o robežās

    def chunks(text):
        for i in range(0, len(text), max_chunk):
            yield text[i:i+max_chunk]

    summary = ""

    for part in chunks(candidate):
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content":
                        "You are an EU public procurement expert. Compare candidate offer "
                        "with requirements and return a structured analysis: Score (0–100), "
                        "Strengths, Weaknesses, Legal Risks, Final Verdict."
                },
                {"role": "user",
                 "content": f"REQUIREMENTS:\n{requirements}\n\nCANDIDATE PART:\n{part}"}
            ]
        )

        summary += "\n" + response.choices[0].message.content

    return summary.strip()


# ==============================
# 6) ZIP kandidātu ielāde
# ==============================
def extract_candidates(zip_path: str):
    results = []
    folder = tempfile.mkdtemp()

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(folder)

        for root, _, files in os.walk(folder):
            for f in files:
                fpath = os.path.join(root, f)
                text = extract_text_from_file(fpath)
                if text.strip():
                    results.append((os.path.splitext(f)[0], text))

    except:
        pass

    return results


# ==============================
# 7) API endpoint — /analyze
# ==============================
@app.post("/analyze", response_class=HTMLResponse)
async def analyze(requirements_file: UploadFile = File(...),
                  candidate_zip: UploadFile = File(...)):

    # Saglabā prasību failu
    req_tmp = tempfile.NamedTemporaryFile(delete=False)
    req_tmp.write(await requirements_file.read())
    req_tmp.close()

    requirements_text = extract_text_from_file(req_tmp.name)

    if not requirements_text.strip():
        return HTMLResponse("<h2>Requirements file unreadable or empty.</h2>", status_code=200)

    # Saglabā kandidātu ZIP
    zip_tmp = tempfile.NamedTemporaryFile(delete=False)
    zip_tmp.write(await candidate_zip.read())
    zip_tmp.close()

    candidates = extract_candidates(zip_tmp.name)

    if not candidates:
        return HTMLResponse("<h2>No readable candidate files found inside ZIP.</h2>", status_code=200)

    # Veicam analīzi
    html = """
    <html><head>
    <style>
    body { font-family: Arial; padding: 20px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px; border: 1px solid #ccc; vertical-align: top; }
    th { background: #eee; }
    pre { white-space: pre-wrap; }
    </style>
    </head><body>
    <h2>Tender Analysis Result</h2>
    <table>
        <tr>
            <th>Candidate</th>
            <th>Evaluation</th>
        </tr>
    """

    for name, text in candidates:
        result = ai_analyze(requirements_text, text)

        html += f"""
        <tr>
            <td>{name}</td>
            <td><pre>{result}</pre></td>
        </tr>
        """

    html += "</table></body></html>"

    return HTMLResponse(content=html, status_code=200)
