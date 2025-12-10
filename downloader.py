# downloader.py — Safe file downloader for Tender Engine v6.0

import os
import tempfile
import requests
from urllib.parse import urlparse

from config import (
    MAX_FILE_SIZE_MB,
    DOWNLOAD_TIMEOUT,
    BUFFER_SIZE,
    ALLOWED_EXTENSIONS,
    DEBUG_MODE,
    log
)

# ======================================================================
# UTILITY: determine extension safely
# ======================================================================

def get_extension_from_url(url: str) -> str:
    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    return ext


# ======================================================================
# UTILITY: ensure extension is allowed
# ======================================================================

def validate_extension(ext: str):
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File extension not allowed: {ext}")


# ======================================================================
# DOWNLOAD FILE FROM URL (STREAMING)
# ======================================================================

def download_file(url: str) -> str:
    """
    Downloads a file from URL safely, checks extension, size, and stores
    it in a temporary file.

    Returns:
        filepath: path to downloaded file
    """

    log(f"Downloading: {url}")

    # Determine extension
    ext = get_extension_from_url(url)
    validate_extension(ext)

    # Start download
    response = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
    response.raise_for_status()

    # Check content-length header (if available)
    file_size = response.headers.get("Content-Length")

    if file_size is not None:
        size_mb = int(file_size) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            raise ValueError(
                f"File too large: {size_mb:.2f} MB (max {MAX_FILE_SIZE_MB} MB)"
            )

    # Create temporary file
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(tmp_fd)  # Close file descriptor, we only use the path

    downloaded_mb = 0.0

    with open(tmp_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=BUFFER_SIZE):
            if chunk:
                f.write(chunk)
                downloaded_mb += len(chunk) / (1024 * 1024)

                if downloaded_mb > MAX_FILE_SIZE_MB:
                    raise ValueError(
                        f"File exceeded max size during download ({downloaded_mb:.2f} MB)"
                    )

    log(f"Downloaded file saved to: {tmp_path} ({downloaded_mb:.2f} MB)")

    return tmp_path


# ======================================================================
# BULK DOWNLOAD WRAPPER
# ======================================================================

def download_multiple(urls: list[str]) -> list[str]:
    """
    Downloads several URLs and returns list of local file paths.
    """
    paths = []
    for url in urls:
        try:
            path = download_file(url)
            paths.append(path)
        except Exception as e:
            log(f"Error downloading {url}: {e}")
            raise e
    return paths
