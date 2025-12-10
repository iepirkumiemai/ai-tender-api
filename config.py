# config.py — Tender Engine v6.0 configuration

import os

# ==============================================================================
# GLOBAL ENGINE SETTINGS
# ==============================================================================

ENGINE_NAME = "AI Tender Engine v6.0"
VERSION = "6.0"

# ==============================================================================
# OPENAI MODEL SETTINGS
# ==============================================================================

# Primary model for requirement extraction + comparison
OPENAI_MODEL = "gpt-4.1"

# Maximum tokens the model should output
MAX_OUTPUT_TOKENS = 2500

# ==============================================================================
# FILE LIMITS
# ==============================================================================

# Maximum allowed file size for downloaded files (in MB)
MAX_FILE_SIZE_MB = 50

# Maximum number of files inside a ZIP archive
MAX_ZIP_FILES = 100

# Maximum depth for nested ZIP extraction
MAX_ZIP_DEPTH = 3

# Allowed document formats
ALLOWED_EXTENSIONS = [
    ".pdf",
    ".docx",
    ".edoc",
    ".txt",
    ".zip"
]

# ==============================================================================
# CHUNKING ENGINE
# ==============================================================================

# Max characters per chunk (before sending to GPT)
CHUNK_SIZE = 5000

# Chunk overlap for better contextual continuity
CHUNK_OVERLAP = 300

# ==============================================================================
# DEBUG SETTINGS
# ==============================================================================

# Enable extremely detailed logging
DEBUG_MODE = True

# Save intermediate structured logs for every chunk
SAVE_DEBUG_CHUNKS = True

# Print logs to console (Railway log)
PRINT_DEBUG = True

# ==============================================================================
# REQUIREMENT EXTRACTION SETTINGS
# ==============================================================================

# Number of requirement categories AI will structure:
REQUIREMENT_CATEGORIES = [
    "legal",
    "technical",
    "qualification",
    "sla",
    "delivery",
    "financial",
    "documentation"
]

# ==============================================================================
# FINAL CLASSIFICATION THRESHOLDS
# ==============================================================================

CONFIDENCE_GREEN = 0.90   # almost full match
CONFIDENCE_YELLOW = 0.60  # partial match or unclear
CONFIDENCE_RED = 0.00     # significant risks or mismatches

# ==============================================================================
# NETWORK SETTINGS
# ==============================================================================

# Maximum time (seconds) for URL download
DOWNLOAD_TIMEOUT = 60

# Buffer size for streaming downloads
BUFFER_SIZE = 1024 * 1024  # 1MB chunks

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

def log(msg: str):
    """Unified debug logger."""
    if PRINT_DEBUG:
        print(f"[DEBUG] {msg}")
