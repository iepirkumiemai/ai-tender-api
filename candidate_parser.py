# candidate_parser.py — Candidate ZIP parsing for Tender Engine v6.0

import os
from urllib.parse import urlparse

from config import (
    DEBUG_MODE,
    log
)

from downloader import download_file
from extractor_zip import extract_zip
from chunker import chunk_text


# ======================================================================
# Utility: derive candidate name from ZIP URL
# ======================================================================

def derive_candidate_name(url: str) -> str:
    """
    Extracts candidate name from URL.
    Example:
       https://site/uploads/companyA_offer.zip
       → companyA_offer
    """

    path = urlparse(url).path
    base = os.path.basename(path)
    name = os.path.splitext(base)[0]
    return name


# ======================================================================
# MAIN PARSER FOR CANDIDATE ZIP
# ======================================================================

def parse_candidate_zip(url: str) -> dict:
    """
    Downloads, extracts, and parses a candidate ZIP file.
    Returns:
        {
          'name': str,
          'files': [...],
          'full_text': str,
          'chunks': [...]
        }
    """

    log(f"=== Parsing candidate ZIP ===")
    log(f"Candidate URL: {url}")

    # -------------------------------------------
    # Download ZIP
    # -------------------------------------------
    zip_path = download_file(url)
    candidate_name = derive_candidate_name(url)

    log(f"Candidate name derived: {candidate_name}")

    # -------------------------------------------
    # Extract all content from ZIP (safe nested ZIP)
    # -------------------------------------------
    text, files = extract_zip(zip_path)

    log(f"Candidate ZIP extracted. Files found: {len(files)}")
    if DEBUG_MODE:
        for f in files:
            log(f"  -> {f}")

    # -------------------------------------------
    # Create one unified text block
    # -------------------------------------------
    full_text = text.strip()

    if not full_text:
        log("WARNING: Candidate ZIP produced no text.")

    # -------------------------------------------
    # Chunk candidate content
    # -------------------------------------------
    chunks = chunk_text(full_text)

    # -------------------------------------------
    # Build final candidate structure
    # -------------------------------------------
    candidate_data = {
        "name": candidate_name,
        "files": files,
        "full_text": full_text,
        "chunks": chunks
    }

    return candidate_data


# ======================================================================
# MULTI-CANDIDATE PARSING
# ======================================================================

def parse_multiple_candidates(url_list: list[str]) -> list[dict]:
    """
    Parses several candidate ZIPs and returns list of candidate profiles.
    """

    results = []

    for url in url_list:
        try:
            candidate = parse_candidate_zip(url)
            results.append(candidate)
        except Exception as e:
            log(f"ERROR parsing candidate ZIP {url}: {e}")
            continue

    log(f"Total candidates parsed: {len(results)}")
    return results
