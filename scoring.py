"""
Confidence scoring — fuse the per-signal scores into one verdict.

Steps (planning.md §2):
  A. weighted average of the AVAILABLE signal scores  -> M
  B. shrink toward 0.5 by how much they disagree       -> P_ai
  C. map P_ai to an attribution via thresholds

Disagreement is measured as the standard deviation of the signal scores,
normalized by its theoretical maximum (0.5), so a perfect 2-vs-2 split gives a
full penalty while a lone outlier among agreeing signals does not dominate.

P_ai (the "AI-likelihood") is what we report as `confidence`.
"""

import statistics

# Signal weights — perplexity (Groq) is strongest, so it counts double.
WEIGHTS = {
    "perplexity": 0.40,
    "burstiness": 0.20,
    "lexical": 0.20,
    "punctuation": 0.20,
}

# Attribution bands on P_ai (planning.md §2).
AI_THRESHOLD = 0.70
HUMAN_THRESHOLD = 0.30

# Max possible population std for values in [0, 1] is 0.5 (a 50/50 split of 0s
# and 1s). Dividing by it scales "disagreement" into [0, 1].
_MAX_STD = 0.5


def _clamp01(x):
    return max(0.0, min(1.0, float(x)))


def attribution_for(p_ai):
    """Map a 0-1 AI-likelihood to an attribution label."""
    if p_ai >= AI_THRESHOLD:
        return "likely_ai"
    if p_ai < HUMAN_THRESHOLD:
        return "likely_human"
    return "uncertain"


def _score_of(value):
    """Accept either a raw float or a signal dict {'score':..,'available':..}."""
    if isinstance(value, dict):
        return value.get("score"), value.get("available", True)
    return value, True


def fuse(signals):
    """
    Combine signal results into a single verdict.

    `signals` is a dict of {name: signal_dict} (or {name: float}). Signals that
    abstained (available=False) are dropped, and the remaining weights are
    renormalized — a "no information" signal never votes.

    Returns:
      {
        "confidence":    P_ai (0-1),
        "attribution":   "likely_ai" | "uncertain" | "likely_human",
        "weighted_mean": M,             # raw blended score before the penalty
        "disagreement":  0-1,           # normalized std of the voting signals
        "signals_used":  [names...],    # which signals actually voted
      }
    """
    present = {}
    for name, value in signals.items():
        if name not in WEIGHTS:
            continue
        score, available = _score_of(value)
        if not available or score is None:
            continue
        present[name] = _clamp01(score)

    if not present:
        return {"confidence": 0.5, "attribution": "uncertain",
                "weighted_mean": 0.5, "disagreement": 0.0, "signals_used": []}

    # A. Weighted average (renormalized over whatever signals voted).
    total_w = sum(WEIGHTS[k] for k in present)
    weighted_mean = sum(WEIGHTS[k] * present[k] for k in present) / total_w

    # B. Disagreement penalty: normalized std, pull toward 0.5.
    values = list(present.values())
    disagreement = min(1.0, statistics.pstdev(values) / _MAX_STD) if len(values) >= 2 else 0.0
    p_ai = _clamp01(0.5 + (weighted_mean - 0.5) * (1 - disagreement))

    # C. Threshold into a verdict.
    return {
        "confidence": round(p_ai, 3),
        "attribution": attribution_for(p_ai),
        "weighted_mean": round(weighted_mean, 3),
        "disagreement": round(disagreement, 3),
        "signals_used": sorted(present),
    }


# Quick manual check: `python scoring.py`
if __name__ == "__main__":
    cases = {
        "all agree (AI)":      {"perplexity": 0.90, "burstiness": 0.85, "lexical": 0.80, "punctuation": 0.80},
        "all agree (human)":   {"perplexity": 0.10, "burstiness": 0.05, "lexical": 0.00, "punctuation": 0.20},
        "human + abstention":  {"perplexity": 0.20, "burstiness": 0.00, "lexical": 0.00,
                                "punctuation": {"score": 0.5, "available": False}},
        "lone noisy dissent":  {"perplexity": 0.90, "burstiness": 0.73, "lexical": 1.00, "punctuation": 0.21},
        "poet (1 vs 3)":       {"perplexity": 0.20, "burstiness": 0.70, "lexical": 0.60, "punctuation": 0.60},
        "true 2-vs-2 split":   {"perplexity": 0.90, "burstiness": 0.90, "lexical": 0.10, "punctuation": 0.10},
    }
    for label, scores in cases.items():
        r = fuse(scores)
        print(f"[{label:>18}] P_ai={r['confidence']:.2f}  {r['attribution']:>13}  "
              f"(mean={r['weighted_mean']:.2f}, disagree={r['disagreement']:.2f}, "
              f"used={len(r['signals_used'])})")
