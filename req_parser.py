# req_parser.py — Ultra-precise requirement extraction for Tender Engine v6.0

import json
from openai import OpenAI

from config import (
    OPENAI_MODEL,
    REQUIREMENT_CATEGORIES,
    DEBUG_MODE,
    MAX_OUTPUT_TOKENS,
    log
)

from chunker import chunk_text


# ================================================================
# Initialize OpenAI client
# ================================================================

client = OpenAI()


# ================================================================
# REQUIREMENT EXTRACTION PROMPT
# Ultra precise mode
# ================================================================

def build_requirement_prompt(chunk: str) -> str:
    """
    Builds the system+user prompt for extracting requirements from chunk.
    """

    categories_list = "\n".join(f"- {c}" for c in REQUIREMENT_CATEGORIES)

    return f"""
You are an AI Tender Document Analyzer. Extract ALL explicit and implied REQUIREMENTS from the following text chunk.

The requirements MUST be structured into these categories:

{categories_list}

Rules:

1. Extract ONLY requirements, NOT explanations.
2. Each requirement must be short, atomic, and precise.
3. Include legal obligations, certifications, technical conditions, SLA, delivery terms, financial requirements, documentation requirements.
4. Even partial or ambiguous requirements MUST BE INCLUDED.
5. If requirement could belong to several categories, choose the closest match.
6. Return ONLY valid JSON in this exact structure:

{{
  "legal": [],
  "technical": [],
  "qualification": [],
  "sla": [],
  "delivery": [],
  "financial": [],
  "documentation": []
}}

Now extract requirements from this chunk:
----
{chunk}
----
"""


# ================================================================
# CLEAN + MERGE RESULTS
# ================================================================

def merge_requirement_results(results: list[dict]) -> dict:
    """
    Merge all chunk results into unified requirement structure.
    """

    final = {cat: [] for cat in REQUIREMENT_CATEGORIES}

    for r in results:
        for cat in REQUIREMENT_CATEGORIES:
            if cat in r and isinstance(r[cat], list):
                for item in r[cat]:
                    cleaned = item.strip()
                    if cleaned and cleaned not in final[cat]:
                        final[cat].append(cleaned)

    return final


# ================================================================
# MAIN EXTRACTION FUNCTION
# ================================================================

def extract_requirements(full_text: str) -> tuple[dict, dict]:
    """
    Extracts ultra-precise tender requirements from ALL requirement documents.
    Returns:
        - final structured requirement dictionary
        - debug info
    """

    log("Starting requirement extraction...")

    chunks = chunk_text(full_text)
    chunk_results = []
    debug_raw_ai = []

    for idx, chunk in enumerate(chunks):

        log(f"Sending requirement chunk {idx+1}/{len(chunks)} to GPT-4.1")

        prompt = build_requirement_prompt(chunk)

        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0
            )
            raw = response.choices[0].message.content
            debug_raw_ai.append(raw)

            parsed = json.loads(raw)
            chunk_results.append(parsed)

            log(f"Requirement chunk {idx+1} parsed successfully.")

        except Exception as e:
            log(f"Requirement extraction failure at chunk {idx+1}: {e}")
            continue

    # Merge all chunk results
    final_requirements = merge_requirement_results(chunk_results)

    debug_info = {
        "chunks": len(chunks),
        "raw_ai_outputs": debug_raw_ai if DEBUG_MODE else None,
        "merged_requirements": final_requirements
    }

    return final_requirements, debug_info
