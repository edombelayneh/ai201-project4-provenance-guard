"""
Provenance Guard — Flask app.

M3: POST /submit route stub + Signal 1 (perplexity via Groq).
Fusion/labels (M4) and appeals/audit log (M5) are wired in later — the
response shape below is intentionally partial and marked accordingly.
"""

import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from signals import perplexity_score

load_dotenv()

app = Flask(__name__)

# Input guards (see planning.md §5 — min-length guard avoids judging tiny texts).
MIN_CHARS = 40
MAX_CHARS = 10_000


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/submit")
def submit():
    """
    Accept text for attribution analysis.

    M3 scope: validate input and run Signal 1. `result`, `confidence`, and
    `label` are placeholders until the scorer (M4) and labels (M5) land.
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

    # --- Detection pipeline (M3: one signal) ---
    signals = {
        "perplexity": perplexity_score(text),
        # "burstiness":  ...   # added in M4
        # "lexical":     ...   # added in M4
        # "punctuation": ...   # added in M4
    }

    return jsonify({
        "content_id": str(uuid.uuid4()),
        "creator_id": creator_id,
        "result": None,        # M4: derived from fused score
        "confidence": None,    # M4: P_ai
        "label": None,         # M5: transparency label text
        "signals": signals,
        "status": "classified",
        "timestamp": _now_iso(),
        "_note": "M3 stub — only Signal 1 (perplexity) is active so far.",
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
