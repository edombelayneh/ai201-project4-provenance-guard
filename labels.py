"""
Transparency labels — turn a verdict into the plain-English text a reader sees.

Three variants (planning.md §3), chosen by attribution. The embedded percentage
is pulled from `confidence`, so the label changes with the score in two ways:
the variant flips at the thresholds, and the percentage moves within a variant.
"""


def _pct(x):
    """Render a 0-1 value as a whole-number percentage."""
    return round(x * 100)


def make_label(attribution, confidence):
    """
    Map a verdict to its transparency label text.

    `confidence` is P_ai (AI-likelihood). For a human verdict we show the
    flipped value (1 - P_ai) so the percentage describes the verdict on screen.
    """
    if attribution == "likely_ai":
        return (
            f"🤖 Likely AI-generated. Our analysis found strong signs this text was "
            f"written by an AI tool (about {_pct(confidence)}% confidence). This is an "
            f"automated estimate, not proof. If you wrote this yourself, you can appeal."
        )
    if attribution == "likely_human":
        return (
            f"✍️ Likely human-written. Our analysis found strong signs this text was "
            f"written by a person (about {_pct(1 - confidence)}% confidence). This is an "
            f"automated estimate, not proof."
        )
    # uncertain (or anything unexpected) falls back to the cautious label
    return (
        f"❓ Uncertain. Our analysis couldn't confidently tell whether this text was "
        f"written by a person or an AI (about {_pct(confidence)}% leaning AI). "
        f"Please treat this result with caution."
    )


# Quick manual check: `python labels.py`
if __name__ == "__main__":
    samples = [
        ("likely_ai", 0.95),
        ("likely_ai", 0.72),
        ("likely_human", 0.18),
        ("uncertain", 0.55),
        ("uncertain", 0.51),
    ]
    for attribution, conf in samples:
        print(f"[{attribution} @ {conf}]")
        print("  " + make_label(attribution, conf))
        print()
