"""
Detection signals.

Each signal takes raw text and returns a dict:
    {"score": float in [0, 1], "note": str, "available": bool}
where 0 = looks human, 1 = looks AI.

`available` is False when the signal had nothing real to measure (an
abstention, e.g. too few sentences, no punctuation evidence, or a Groq error).
The scorer drops abstentions so a "no information" signal never votes.

Signals: 1 perplexity (Groq), 2 burstiness, 3 lexical tells, 4 punctuation.
"""

import json
import os
import re
import statistics

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
        return {"score": 0.5, "note": "perplexity unavailable: GROQ_API_KEY not set",
                "available": False}

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
        return {"score": 0.5, "note": f"perplexity unavailable (Groq error): {exc}",
                "available": False}

    score, reason = _extract_score(raw)
    note = f"predictability {score:.2f}"
    if reason:
        note += f" — {reason}"
    return {"score": score, "note": note, "available": True}


# Split on sentence-enders AND line breaks, so line-broken poems are measured too.
_SENTENCE_SPLIT = re.compile(r"[.!?\n]+")

# CV at which a text is considered fully "human-bumpy" (planning.md §2: human ~0.5).
_CV_HUMAN_ANCHOR = 0.6

# Variance from a handful of sentences is noisy, so burstiness abstains below
# this many sentences rather than voting on an unreliable estimate.
_MIN_SENTENCES = 4


def burstiness_score(text):
    """
    Signal 2 — burstiness (variance in sentence length).

    Humans vary sentence length a lot (high variance); AI tends to keep them
    uniform (low variance). We measure the coefficient of variation
    (CV = std / mean of sentence word-counts) and map low CV -> high AI score.

    Returns {"score": float in [0,1], "note": str}. Needs >= _MIN_SENTENCES
    sentences for a stable estimate; otherwise it abstains.
    """
    sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    lengths = [len(s.split()) for s in sentences if s.split()]

    if len(lengths) < _MIN_SENTENCES:
        return {"score": 0.5, "note": f"burstiness n/a — only {len(lengths)} sentence(s)",
                "available": False}

    mean = statistics.mean(lengths)
    if mean == 0:
        return {"score": 0.5, "note": "burstiness n/a — empty sentences",
                "available": False}

    cv = statistics.pstdev(lengths) / mean
    # Low CV (uniform) -> high AI score; high CV (bumpy) -> low AI score.
    score = _clamp01(1 - cv / _CV_HUMAN_ANCHOR)
    note = f"sentence-length CV {cv:.2f} over {len(lengths)} sentences"
    return {"score": score, "note": note, "available": True}


# Phrases AI assistants overuse. Lowercase; matched as substrings/word-boundaries.
_AI_TELLS = [
    "delve", "tapestry", "it's important to note", "it is important to note",
    "in today's fast-paced world", "navigate the complexities", "a testament to",
    "leveraging", "unlock your full potential", "unlock the full potential",
    "cornerstone", "realm of", "underscore", "it's worth noting",
    "it is worth noting", "plays a crucial role", "plays a vital role",
    "ever-evolving", "ever-changing", "game-changer", "dive into", "embark on",
    "elevate", "seamless", "robust", "foster", "moreover", "furthermore",
    "in conclusion", "rich tapestry", "at the end of the day", "shed light on",
    "when it comes to", "the world of", "a myriad of", "paradigm",
]

# Three or more words joined by ", " ending in ", and X" — the "rule of three".
_RULE_OF_THREE = re.compile(r"\b\w+,\s+\w+,\s+and\s+\w+", re.IGNORECASE)
# Em-dash: real em-dash, or a double hyphen used as one.
_EM_DASH = re.compile(r"—|--")

# Tells-per-100-words at which lexical score saturates to 1.0 (planning.md §2).
_LEXICAL_SATURATION = 3.0


def lexical_score(text):
    """
    Signal 3 — lexical AI-tells.

    Counts known AI-overused phrases per 100 words. More tells -> higher AI
    score. Returns {"score": float in [0,1], "note": str}.
    """
    words = re.findall(r"\b\w+\b", text)
    if not words:
        return {"score": 0.5, "note": "lexical n/a — no words", "available": False}

    lower = text.lower()
    hits = sum(lower.count(phrase) for phrase in _AI_TELLS)
    per_100 = hits / len(words) * 100
    score = _clamp01(per_100 / _LEXICAL_SATURATION)
    note = f"{hits} AI-tell phrase(s), {per_100:.1f} per 100 words"
    return {"score": score, "note": note, "available": True}


def punctuation_score(text):
    """
    Signal 4 — punctuation patterns (an AI-tell DETECTOR).

    Looks for punctuation habits AI overuses: frequent em-dashes, "rule of
    three" lists, and machine-regular comma spacing. Each tell counts only when
    it is actually present — absence of a tell is treated as *no evidence*, not
    as evidence of a human. So this signal only ever argues "AI-ish" or
    abstains; it never votes "human" just because punctuation looks plain.

    Returns {"score": float in [0,1], "note": str, "available": bool}. Abstains
    (available=False) when no AI tells are found.
    """
    words = re.findall(r"\b\w+\b", text)
    if not words:
        return {"score": 0.5, "note": "punctuation n/a — no words", "available": False}

    tells = []

    # Tell 1: em-dash density (~2 per 100 words saturates). Counts only if present.
    em_dashes = len(_EM_DASH.findall(text))
    if em_dashes:
        tells.append(_clamp01(em_dashes / len(words) * 100 / 2.0))

    # Tell 2: rule-of-three list constructions (~2 saturates). Counts only if present.
    triples = len(_RULE_OF_THREE.findall(text))
    if triples:
        tells.append(_clamp01(triples / 2.0))

    # Tell 3: machine-regular comma spacing. Counts ONLY when notably regular —
    # irregular commas are normal human writing, i.e. absence of an AI tell.
    regular = False
    comma_positions = [i for i, w in enumerate(text.split()) if w.endswith(",")]
    if len(comma_positions) >= 3:
        gaps = [b - a for a, b in zip(comma_positions, comma_positions[1:])]
        if statistics.mean(gaps) > 0:
            regularity = _clamp01(1 - statistics.pstdev(gaps) / statistics.mean(gaps) / 0.8)
            if regularity > 0.5:
                tells.append(regularity)
                regular = True

    if not tells:
        return {"score": 0.5, "note": "punctuation n/a — no AI tells found",
                "available": False}

    score = sum(tells) / len(tells)
    note = f"{em_dashes} em-dash, {triples} rule-of-three list(s)"
    if regular:
        note += ", regular comma rhythm"
    return {"score": score, "note": note, "available": True}


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
