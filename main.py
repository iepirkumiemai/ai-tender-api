from fastapi import FastAPI, UploadFile, File
import tempfile
import os

app = FastAPI()

@app.get("/")
def root():
    return {"status": "OK"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    temp_dir = tempfile.mkdtemp(prefix="upload_")
    file_path = os.path.join(temp_dir, file.filename)

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    return {
        "status": "uploaded",
        "filename": file.filename,
        "temp_path": file_path
    }
