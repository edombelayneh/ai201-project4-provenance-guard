"""
Provenance Guard — Flask app.

M4: POST /submit runs all four signals, fuses them into a single confidence
score, and records the full decision in the audit log. Transparency labels and
the appeals workflow (M5) come next, so `label` is still null.
"""

import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request

import audit
from scoring import fuse
from signals import (
    burstiness_score,
    lexical_score,
    perplexity_score,
    punctuation_score,
)

load_dotenv()

app = Flask(__name__)

# Input guards (see planning.md §5 — min-length guard avoids judging tiny texts).
MIN_CHARS = 40
MAX_CHARS = 10_000


def _now_iso():
    # e.g. "2026-06-28T21:32:10.123Z"
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/submit")
def submit():
    """
    Accept text for attribution analysis, classify it, and record the decision
    in the audit log.
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    # --- Validation ---
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Field 'text' is required and must be a non-empty string."}), 400
    text = text.strip()
    if len(text) < MIN_CHARS:
        return jsonify({"error": f"Text too short to analyze (min {MIN_CHARS} characters)."}), 400
    if len(text) > MAX_CHARS:
        return jsonify({"error": f"Text too long (max {MAX_CHARS} characters)."}), 400

    # --- Detection pipeline: all four signals ---
    signals = {
        "perplexity": perplexity_score(text),
        "burstiness": burstiness_score(text),
        "lexical": lexical_score(text),
        "punctuation": punctuation_score(text),
    }

    # --- Fuse into a single verdict (weighted mean + disagreement penalty) ---
    # Pass full signal dicts so fuse() can drop abstentions (available=False).
    verdict = fuse(signals)
    signal_scores = {name: sig["score"] for name, sig in signals.items()}

    content_id = str(uuid.uuid4())
    timestamp = _now_iso()

    # --- Audit log: structured entry for every decision ---
    audit.log_decision({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": verdict["attribution"],
        "confidence": verdict["confidence"],       # fused P_ai
        "llm_score": signal_scores["perplexity"],  # raw Groq signal (kept separate)
        "signal_scores": signal_scores,
        "signals_used": verdict["signals_used"],
        "weighted_mean": verdict["weighted_mean"],
        "disagreement": verdict["disagreement"],
        "status": "classified",
    })

    return jsonify({
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": verdict["attribution"],
        "confidence": verdict["confidence"],
        "label": None,                # M5: transparency label text
        "signals": signals,
        "scoring": {
            "weighted_mean": verdict["weighted_mean"],
            "disagreement": verdict["disagreement"],
            "signals_used": verdict["signals_used"],
        },
        "status": "classified",
        "timestamp": timestamp,
    })


@app.get("/log")
def get_log():
    """
    Return audit log entries as JSON for documentation/grading visibility.
    Optional filters: ?content_id=... and ?limit=... (defaults to last 50).
    NOTE: in a real system this endpoint would require auth.
    """
    content_id = request.args.get("content_id")
    limit = request.args.get("limit", default=50, type=int)
    return jsonify({"entries": audit.read_log(content_id=content_id, limit=limit)})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
