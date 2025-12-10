# ai_compare.py — Requirement vs Candidate comparison engine for Tender Engine v6.0

import json
from openai import OpenAI
from config import (
    OPENAI_MODEL,
    DEBUG_MODE,
    MAX_OUTPUT_TOKENS,
    log
)


client = OpenAI()


# =====================================================================
# BUILD PRASĪBU SALĪDZINĀŠANAS PROMPTU
# =====================================================================

def build_compare_prompt(requirement: str, candidate_text: str) -> str:
    """
    Builds system prompt to compare one requirement vs candidate text.
    """

    return f"""
You are an AI Tender Compliance Auditor.

Your task: evaluate whether the candidate OFFER satisfies the following REQUIREMENT.

RULES:

1. FULLY explicit match → GREEN
2. Partially met or ambiguous → YELLOW
3. Not met or contradicted → RED

Return STRICT JSON:

{{
 "status": "green|yellow|red",
 "reason": {{
     "issue": "...",
     "risk": "...",
     "note": "..."
 }},
 "icon": "🟢|🟡|🔴"
}}

----------------------------------------
REQUIREMENT:
{requirement}

----------------------------------------
CANDIDATE CONTENT:
{candidate_text}
----------------------------------------
"""


# =====================================================================
# SINGLE REQUIREMENT EVALUATION
# =====================================================================

def evaluate_requirement(requirement: str, candidate_full_text: str) -> dict:
    """
    Evaluates ONE requirement against entire candidate text.
    """

    log(f"Comparing requirement: {requirement[:60]}...")

    prompt = build_compare_prompt(requirement, candidate_full_text)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0
        )

        raw = response.choices[0].message.content
        if DEBUG_MODE:
            log(f"RAW AI OUTPUT:\n{raw}\n")

        parsed = json.loads(raw)

        return parsed

    except Exception as e:
        log(f"Evaluation error: {e}")

        # Fail-safe → mark requirement as unclear
        return {
            "status": "yellow",
            "icon": "🟡",
            "reason": {
                "issue": "AI evaluation error",
                "risk": "Requirement could not be fully evaluated",
                "note": str(e)
            }
        }


# =====================================================================
# CANDIDATE vs ALL REQUIREMENTS
# =====================================================================

def evaluate_candidate(requirements: dict, candidate: dict) -> dict:
    """
    Evaluates ALL requirements against one candidate.
    """

    log(f"=== Evaluating Candidate: {candidate['name']} ===")

    results = []
    total_reqs = 0
    green = 0
    yellow = 0
    red = 0

    # Flatten requirement dictionary into a list
    for category, items in requirements.items():
        for req in items:
            total_reqs += 1
            eval_result = evaluate_requirement(req, candidate["full_text"])

            eval_result["requirement"] = req
            eval_result["category"] = category

            results.append(eval_result)

            status = eval_result.get("status", "yellow")
            if status == "green":
                green += 1
            elif status == "yellow":
                yellow += 1
            else:
                red += 1

    # FINAL DECISION LOGIC
    if red > 0:
        final_status = "red"
        icon = "🔴"
    elif yellow > 0:
        final_status = "yellow"
        icon = "🟡"
    else:
        final_status = "green"
        icon = "🟢"

    # Confidence = green / total
    confidence = round(green / max(1, total_reqs), 3)

    # SUMMARY GENERATION
    summary_prompt = f"""
Summarize tender compliance evaluation.

Return JSON:
{{
 "overview": "...",
 "strengths": [],
 "risks": [],
 "unclear": []
}}
    
Evaluation data:
{json.dumps(results)}
"""

    try:
        summary_resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": summary_prompt}],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0
        )

        summary_json = json.loads(summary_resp.choices[0].message.content)

    except Exception as e:
        log(f"Summary generation failed: {e}")
        summary_json = {
            "overview": "",
            "strengths": [],
            "risks": [],
            "unclear": []
        }

    return {
        "candidate": candidate["name"],
        "files": candidate["files"],
        "status": final_status,
        "icon": icon,
        "confidence": confidence,
        "requirements_total": total_reqs,
        "green": green,
        "yellow": yellow,
        "red": red,
        "findings": results,
        "summary": summary_json
    }
