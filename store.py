"""
Content store — the current state of each piece of content, keyed by content_id.

Unlike the append-only audit log, this is MUTABLE: an appeal flips a content's
status to "under_review". Backed by a JSON file so it survives restarts. Held in
memory and rewritten on every change (fine for this project's volume).
"""

import json
import os
import threading
from pathlib import Path

STORE_PATH = Path(os.environ.get("CONTENT_STORE_PATH", "content_store.json"))

_lock = threading.Lock()


def _load():
    if not STORE_PATH.exists():
        return {}
    try:
        with STORE_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# Loaded once at import; mutations are persisted back via _save().
_content = _load()


def _save():
    with STORE_PATH.open("w", encoding="utf-8") as f:
        json.dump(_content, f, ensure_ascii=False, indent=2)


def save_content(record):
    """Insert a new content record (must include 'content_id')."""
    with _lock:
        _content[record["content_id"]] = record
        _save()
    return record


def get_content(content_id):
    """Return the record for content_id, or None if unknown."""
    return _content.get(content_id)


def update_content(content_id, **changes):
    """Apply field changes to an existing record. Returns the updated record, or None."""
    with _lock:
        record = _content.get(content_id)
        if record is None:
            return None
        record.update(changes)
        _save()
        return record


def by_status(status):
    """Return all records currently in the given status (e.g. the review queue)."""
    return [r for r in _content.values() if r.get("status") == status]
