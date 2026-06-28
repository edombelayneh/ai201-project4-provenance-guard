"""
Provenance Guard — Flask app.

M5: POST /submit runs all four signals, fuses them into a confidence score,
attaches a plain-English transparency label, and records the decision in the
audit log. (POST /appeal is added next.)
"""

import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import audit
import store
from labels import make_label
from scoring import fuse
from signals import (
    burstiness_score,
    lexical_score,
    perplexity_score,
    punctuation_score,
)

load_dotenv()

app = Flask(__name__)

# Rate limiting (per client IP). Limits are generous for a real writer checking
# their own work, but stop a script from flooding the endpoint — which also
# protects the paid Groq API call each /submit makes. See README for rationale.
SUBMIT_RATE_LIMIT = "10 per minute;100 per day"
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# Input guards (see planning.md §5 — min-length guard avoids judging tiny texts).
MIN_CHARS = 40
MAX_CHARS = 10_000


@app.errorhandler(429)
def ratelimit_exceeded(e):
    """Return a clean JSON 429 instead of Flask-Limiter's default HTML."""
    return jsonify({
        "error": "Rate limit exceeded. Please slow down and try again later.",
        "limit": str(e.description),
    }), 429


def _now_iso():
    # e.g. "2026-06-28T21:32:10.123Z"
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/submit")
@limiter.limit(SUBMIT_RATE_LIMIT)
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

    # --- Transparency label (one of three variants, score-dependent) ---
    label = make_label(verdict["attribution"], verdict["confidence"])

    content_id = str(uuid.uuid4())
    timestamp = _now_iso()

    # --- Audit log: structured entry for every decision ---
    audit.log_decision({
        "event": "classification",
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": verdict["attribution"],
        "confidence": verdict["confidence"],       # fused P_ai
        "label": label,                            # transparency label shown to reader
        "llm_score": signal_scores["perplexity"],  # raw Groq signal (kept separate)
        "signal_scores": signal_scores,
        "signals_used": verdict["signals_used"],
        "weighted_mean": verdict["weighted_mean"],
        "disagreement": verdict["disagreement"],
        "status": "classified",
    })

    # --- Content store: current state, so appeals can update the status later ---
    store.save_content({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "text": text,                              # kept so a reviewer can read it
        "attribution": verdict["attribution"],
        "confidence": verdict["confidence"],
        "label": label,
        "signal_scores": signal_scores,
        "status": "classified",
    })

    return jsonify({
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": verdict["attribution"],
        "confidence": verdict["confidence"],
        "label": label,
        "signals": signals,
        "scoring": {
            "weighted_mean": verdict["weighted_mean"],
            "disagreement": verdict["disagreement"],
            "signals_used": verdict["signals_used"],
        },
        "status": "classified",
        "timestamp": timestamp,
    })


@app.post("/appeal")
def appeal():
    """
    Let a creator contest a classification. Updates the content's status to
    'under_review', logs the appeal alongside the original decision in the audit
    log, and returns a confirmation. No automated re-classification.
    """
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    # --- Validation ---
    if not isinstance(content_id, str) or not content_id.strip():
        return jsonify({"error": "Field 'content_id' is required."}), 400
    if not isinstance(creator_reasoning, str) or not creator_reasoning.strip():
        return jsonify({"error": "Field 'creator_reasoning' is required."}), 400

    record = store.get_content(content_id)
    if record is None:
        return jsonify({"error": f"Unknown content_id: {content_id}"}), 404

    appeal_id = str(uuid.uuid4())
    timestamp = _now_iso()
    reasoning = creator_reasoning.strip()

    # --- Update current state: status -> under_review ---
    store.update_content(
        content_id,
        status="under_review",
        appeal_id=appeal_id,
        appeal_reasoning=reasoning,
        appealed_at=timestamp,
    )

    # --- Audit log: appeal event, alongside the original decision ---
    audit.log_decision({
        "event": "appeal",
        "content_id": content_id,
        "appeal_id": appeal_id,
        "creator_id": record.get("creator_id"),
        "timestamp": timestamp,
        "status": "under_review",
        "appeal_reasoning": reasoning,
        # carry the original verdict so the appeal sits next to what it contests
        "original_attribution": record.get("attribution"),
        "original_confidence": record.get("confidence"),
    })

    return jsonify({
        "content_id": content_id,
        "appeal_id": appeal_id,
        "status": "under_review",
        "logged_at": timestamp,
        "message": "Appeal received. This content is now under review.",
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


@app.get("/review-queue")
def review_queue():
    """The human reviewer's view: all content currently awaiting review."""
    return jsonify({"under_review": store.by_status("under_review")})


@app.get("/content/<content_id>")
def get_content(content_id):
    """Check a single content record's current status."""
    record = store.get_content(content_id)
    if record is None:
        return jsonify({"error": f"Unknown content_id: {content_id}"}), 404
    return jsonify(record)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
