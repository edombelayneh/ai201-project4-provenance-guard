"""
Provenance Guard — Streamlit front-end.

A friendly UI over the Flask API: paste text, see the verdict + transparency
label, file an appeal, and browse appeals — no curl needed.

Run (in two terminals):
    1)  ./.venv/bin/python app.py                 # the API on 127.0.0.1:5000
    2)  ./.venv/bin/streamlit run ui.py           # this UI
"""

import os

import requests
import streamlit as st

API_BASE = os.environ.get("PROVGUARD_API", "http://127.0.0.1:5000")

st.set_page_config(page_title="Provenance Guard", page_icon="🛡️")


def api_post(path, payload):
    """POST to the Flask API; return (ok, data) or a friendly error."""
    try:
        res = requests.post(f"{API_BASE}{path}", json=payload, timeout=30)
    except requests.exceptions.RequestException:
        return False, {"error": f"Could not reach the API at {API_BASE}. "
                               f"Is the Flask server running? (./.venv/bin/python app.py)"}
    try:
        return res.ok, res.json()
    except ValueError:
        return False, {"error": f"Unexpected response ({res.status_code})."}


def api_get(path):
    """GET from the Flask API; return (ok, data) or a friendly error."""
    try:
        res = requests.get(f"{API_BASE}{path}", timeout=30)
    except requests.exceptions.RequestException:
        return False, {"error": f"Could not reach the API at {API_BASE}. "
                               f"Is the Flask server running? (./.venv/bin/python app.py)"}
    try:
        return res.ok, res.json()
    except ValueError:
        return False, {"error": f"Unexpected response ({res.status_code})."}


st.title("🛡️ Provenance Guard")
st.caption("Check whether a piece of text was likely written by a human or an AI.")

tab_analyze, tab_appeals = st.tabs(["🔍 Analyze", "📋 View Appeals"])


# ======================================================================
# TAB 1 — Analyze + appeal
# ======================================================================
with tab_analyze:
    text = st.text_area(
        "Content",
        height=200,
        placeholder="Paste a poem, story excerpt, or blog post (at least 40 characters)…",
    )
    creator_id = st.text_input("Creator ID (optional)", placeholder="your name or username")

    if st.button("Analyze", type="primary"):
        if not text.strip():
            st.warning("Please paste some text first.")
        else:
            payload = {"text": text}
            if creator_id.strip():
                payload["creator_id"] = creator_id.strip()
            with st.spinner("Analyzing…"):
                ok, data = api_post("/submit", payload)
            if not ok:
                st.error(data.get("error", "Something went wrong."))
                st.session_state.pop("result", None)
            else:
                st.session_state["result"] = data
                st.session_state.pop("appeal_done", None)

    result = st.session_state.get("result")
    if result:
        attribution = result["attribution"]
        confidence = result["confidence"]
        pct = round(confidence * 100)

        st.divider()
        if attribution == "likely_human":
            st.success(result["label"])
        elif attribution == "likely_ai":
            st.error(result["label"])
        else:
            st.warning(result["label"])

        st.write(f"**AI-likelihood:** {pct}%")
        st.progress(confidence)
        st.caption(f"content_id: `{result['content_id']}`")

        with st.expander("Why? See the four signal scores"):
            rows = [
                {
                    "signal": name,
                    "score": f"{sig['score']:.2f}" if sig["available"] else "abstained",
                    "note": sig["note"],
                }
                for name, sig in result["signals"].items()
            ]
            st.table(rows)

        st.divider()
        if st.session_state.get("appeal_done"):
            st.success(st.session_state["appeal_done"])
        else:
            with st.expander("Disagree? Appeal this result"):
                reasoning = st.text_area(
                    "Tell us why (a human will review this)",
                    height=100,
                    placeholder="e.g. I wrote this myself from personal experience…",
                    key="reasoning",
                )
                if st.button("Submit appeal"):
                    if not reasoning.strip():
                        st.warning("Please enter a reason.")
                    else:
                        ok, data = api_post("/appeal", {
                            "content_id": result["content_id"],
                            "creator_reasoning": reasoning.strip(),
                        })
                        if not ok:
                            st.error(data.get("error", "Appeal failed."))
                        else:
                            st.session_state["appeal_done"] = (
                                f"✓ {data['message']} (appeal_id: {data['appeal_id']})"
                            )
                            st.rerun()


# ======================================================================
# TAB 2 — View appeals (filter by username or appeal id)
# ======================================================================
def _history_for(content_id):
    """Fetch and render the full audit history for one content_id."""
    ok, log = api_get(f"/log?content_id={content_id}")
    if not ok:
        st.error(log.get("error", "Could not load history."))
        return
    entries = log.get("entries", [])
    if not entries:
        st.info("No history found.")
        return

    for entry in entries:
        if entry.get("event") == "appeal":
            st.markdown(f"**📨 Appeal** — `{entry['timestamp']}`")
            st.write(f"- Status: **{entry['status']}**")
            st.write(f"- Reason: {entry['appeal_reasoning']}")
            st.write(f"- Contested verdict: {entry['original_attribution']} "
                     f"({entry['original_confidence']})")
        else:
            st.markdown(f"**🧪 Classification** — `{entry['timestamp']}`")
            st.write(f"- Result: **{entry['attribution']}** (confidence {entry['confidence']})")
            st.write(f"- Signal scores: {entry['signal_scores']}")
            st.caption(entry["label"])
        with st.expander("Raw entry (JSON)"):
            st.json(entry)
        st.divider()


with tab_appeals:
    st.subheader("View appeals")
    st.caption("Find appealed items by the creator's username or by an appeal ID.")

    filter_type = st.radio(
        "Filter by", ["Username (creator_id)", "Appeal ID"], horizontal=True
    )
    filter_value = st.text_input("Enter value to search for", key="appeal_filter")

    if st.button("View Appeals", type="primary"):
        value = filter_value.strip()
        if not value:
            st.warning("Please enter a username or appeal ID.")
        else:
            ok, data = api_get("/review-queue")
            if not ok:
                st.error(data.get("error", "Could not load appeals."))
                st.session_state.pop("appeal_matches", None)
            else:
                items = data.get("under_review", [])
                if filter_type.startswith("Username"):
                    matches = [i for i in items if i.get("creator_id") == value]
                else:
                    matches = [i for i in items if i.get("appeal_id") == value]
                st.session_state["appeal_matches"] = matches

    matches = st.session_state.get("appeal_matches")
    if matches is not None:
        if not matches:
            st.info("No appeals found for that value.")
        else:
            st.write(f"Found **{len(matches)}** appealed item(s):")
            # Build a friendly label -> content_id map for the picker.
            options = {
                f"{i['content_id'][:8]}… — {i.get('creator_id') or 'no id'} — "
                f"{i['attribution']} ({i['confidence']})": i["content_id"]
                for i in matches
            }
            choice = st.selectbox("Pick an item to see its full history", list(options))
            st.divider()
            st.markdown("### Full history")
            _history_for(options[choice])
