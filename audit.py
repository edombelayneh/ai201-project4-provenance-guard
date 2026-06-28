"""
Audit log — a structured, append-only record of every attribution decision.

Stored as JSON Lines (one JSON object per line) so writes are append-only and
safe, and reads are easy. Extended in M4 (full signal breakdown) and M5
(appeals attached to entries).
"""

import json
import os
import threading
from pathlib import Path

LOG_PATH = Path(os.environ.get("AUDIT_LOG_PATH", "audit_log.jsonl"))

# Guard concurrent writes (Flask debug server can handle overlapping requests).
_lock = threading.Lock()


def log_decision(entry):
    """Append one structured entry (a dict) to the audit log. Returns the entry."""
    with _lock:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_log(content_id=None, limit=None):
    """
    Read entries back, newest last. Optionally filter by content_id and/or
    return only the last `limit` entries.
    """
    if not LOG_PATH.exists():
        return []

    entries = []
    with LOG_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip any corrupt line rather than crash

    if content_id:
        entries = [e for e in entries if e.get("content_id") == content_id]
    if limit:
        entries = entries[-int(limit):]
    return entries
