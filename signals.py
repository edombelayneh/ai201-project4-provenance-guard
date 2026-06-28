"""
Detection signals.

Each signal takes raw text and returns a dict:
    {"score": float in [0, 1], "note": str}
where 0 = looks human, 1 = looks AI.

M3 implements Signal 1 (perplexity via Groq). Signals 2-4 (burstiness,
lexical tells, punctuation) are added in M4.
"""

import json
import os
import re

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# Anchored prompt so the model returns a stable, calibrated 0-1 scale.
_PERPLEXITY_SYSTEM = (
    "You are a forensic text analyst. You estimate how AI-generated a piece of "
    "text reads, judging ONLY by its statistical predictability and formulaic "
    "smoothness (a proxy for perplexity). Smooth, generic, highly predictable "
    "writing scores HIGH (AI-like). Bumpy, surprising, idiosyncratic writing "
    "scores LOW (human-like).\n\n"
    "Use this scale:\n"
    "  0.0-0.2  very surprising / idiosyncratic word choices (very human)\n"
    "  0.3-0.5  somewhat predictable, a few generic turns\n"
    "  0.5-0.7  fairly smooth and generic\n"
    "  0.8-1.0  extremely smooth, predictable, generic (very AI)\n\n"
    'Respond with ONLY JSON: {"ai_likelihood": <float 0-1>, "reason": "<short phrase>"}'
)


def _clamp01(x):
    """Force a value into [0, 1]."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, x))


def _extract_score(raw_text):
    """Pull an ai_likelihood float out of the model's reply, robustly."""
    # Preferred path: clean JSON.
    try:
        data = json.loads(raw_text)
        return _clamp01(data.get("ai_likelihood")), str(data.get("reason", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: find the first float between 0 and 1 anywhere in the text.
    match = re.search(r"(?:ai_likelihood\"?\s*[:=]\s*)?(0?\.\d+|0|1(?:\.0)?)", raw_text)
    if match:
        return _clamp01(match.group(1)), "parsed from unstructured reply"
    return 0.5, "could not parse a score"


def perplexity_score(text):
    """
    Signal 1 — predictability/perplexity via a Groq LLM-judge.

    Returns {"score": float in [0,1], "note": str}. On any Groq failure it
    degrades gracefully to a neutral 0.5 so the pipeline never crashes.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"score": 0.5, "note": "perplexity unavailable: GROQ_API_KEY not set"}

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=0,
            max_tokens=120,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _PERPLEXITY_SYSTEM},
                {"role": "user", "content": f"Analyze this text:\n\n{text}"},
            ],
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:  # network, auth, rate limit, bad model, etc.
        return {"score": 0.5, "note": f"perplexity unavailable (Groq error): {exc}"}

    score, reason = _extract_score(raw)
    note = f"predictability {score:.2f}"
    if reason:
        note += f" — {reason}"
    return {"score": score, "note": note}


# Quick manual check: `python signals.py`
if __name__ == "__main__":
    samples = {
        "clearly AI": (
            "In today's fast-paced world, it is important to note that effective "
            "communication remains a cornerstone of success. By leveraging diverse "
            "strategies, individuals can navigate the complexities of modern life "
            "and unlock their full potential."
        ),
        "messy human": (
            "honestly? i dunno. the bus was late again — third time this week — and "
            "i just stood there. cold. thinking about nothing, really. maybe lunch."
        ),
        "too short": "Hello there.",
    }
    for label, txt in samples.items():
        result = perplexity_score(txt)
        print(f"[{label:>11}] score={result['score']:.2f}  note={result['note']}")
