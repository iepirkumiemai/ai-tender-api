import os
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

app = FastAPI(
    title="ai-tender-api",
    version="0.2.0",
    description="AI Tender dokumentu apstrādes un analītikas API"
)

@app.get("/")
async def root():
    return {"status": "OK", "service": "ai-tender-api"}

@app.get("/health")
async def health():
    return JSONResponse({"health": "UP"})


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    temp_dir = tempfile.mkdtemp(prefix="uploaded_")
    file_path = os.path.join(temp_dir, file.filename)

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return {
        "status": "OK",
        "filename": file.filename,
        "size_bytes": len(content),
        "saved_to": file_path,
        "temp_dir": temp_dir
    }
