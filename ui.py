"""
Provenance Guard — Streamlit front-end.

A friendly UI over the Flask API: paste text, see the verdict + transparency
label, and file an appeal — no curl needed.

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
    """POST to the Flask API; return (ok, data) or surface a friendly error."""
    try:
        res = requests.post(f"{API_BASE}{path}", json=payload, timeout=30)
    except requests.exceptions.RequestException:
        return False, {"error": f"Could not reach the API at {API_BASE}. "
                               f"Is the Flask server running? (./.venv/bin/python app.py)"}
    try:
        data = res.json()
    except ValueError:
        data = {"error": f"Unexpected response ({res.status_code})."}
    return res.ok, data


# --- Header ---
st.title("🛡️ Provenance Guard")
st.caption("Check whether a piece of text was likely written by a human or an AI.")

# --- Submission form ---
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
            st.session_state.pop("appeal_done", None)  # reset any prior appeal state


# --- Result ---
result = st.session_state.get("result")
if result:
    attribution = result["attribution"]
    confidence = result["confidence"]
    pct = round(confidence * 100)

    st.divider()

    # Color-coded verdict using Streamlit's built-in boxes.
    if attribution == "likely_human":
        st.success(result["label"])
    elif attribution == "likely_ai":
        st.error(result["label"])
    else:
        st.warning(result["label"])

    # AI-likelihood meter.
    st.write(f"**AI-likelihood:** {pct}%")
    st.progress(confidence)
    st.caption(f"content_id: `{result['content_id']}`")

    # Signal breakdown.
    with st.expander("Why? See the four signal scores"):
        rows = []
        for name, sig in result["signals"].items():
            rows.append({
                "signal": name,
                "score": f"{sig['score']:.2f}" if sig["available"] else "abstained",
                "note": sig["note"],
            })
        st.table(rows)

    # --- Appeal ---
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
