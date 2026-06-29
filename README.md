# Provenance Guard

Submit a piece of text and the app guesses if it was written by a **human** or an **AI**.
It gives a **confidence score**, shows a plain-English **label**, lets creators **appeal**,
and saves every decision to an **audit log**.

It uses **four signals** combined into one score. When the signals disagree, the app says
"uncertain" instead of blaming someone wrongly. Full design is in [planning.md](planning.md).

---

## ⚠️ Use `127.0.0.1`, not `localhost` (port 5000 on macOS)

On macOS, AirPlay Receiver also uses port 5000 (on `localhost`). The app uses `127.0.0.1`.

- `http://127.0.0.1:5000` → the app ✅
- `http://localhost:5000` → AirPlay, returns `403` ❌

So always use `http://127.0.0.1:5000`. (Or turn off *Settings → General → AirDrop & Handoff →
AirPlay Receiver*.)

---

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
echo "GROQ_API_KEY=your_key_here" > .env      # needed for the perplexity signal
```

## Run

API (terminal 1):
```bash
./.venv/bin/python app.py                      # http://127.0.0.1:5000
```

## Web UI (Streamlit)

The easiest way to try everything is the **Streamlit** web app. No curl needed — it's all
point-and-click. Start it in a second terminal (the API must also be running):

```bash
./.venv/bin/streamlit run ui.py                # http://localhost:8501
```

It has two tabs:

- **🔍 Analyze** — paste text → **Analyze** → see the label, the AI-likelihood bar, and the
  four signal scores. To contest a result, open **"Disagree? Appeal this result"**, type a
  reason, and submit.
- **📋 View Appeals** — search appealed items by **username** or **appeal ID**, pick one, and
  see its full history (original verdict + the appeal).

So submitting, appealing, and checking appeal status can all be tested right in the UI.

## Quick test
```bash
./test.sh            # starts the server, runs sample requests, stops it
./test.sh signal     # runs the signals directly (no server)
```

---

## The four signals — and why

Each signal reads the text and returns a score from 0 to 1 (0 = human, 1 = AI). A signal can
also **abstain** when it has nothing useful to measure.

| Signal | What it looks at | Weight |
|---|---|---|
| **Perplexity** (Groq) | How predictable the words are | 0.40 |
| **Burstiness** | How much sentence length changes | 0.20 |
| **Lexical tells** | AI-favorite phrases ("delve", "tapestry") | 0.20 |
| **Punctuation** | AI punctuation habits (em-dashes, neat lists) | 0.20 |

These four are chosen because they **fail in different ways**, so when one is wrong the others
can still be right:

- **Perplexity** is about meaning, so it catches AI even when the words look normal. It is the
  strongest signal, so it gets the most weight. Its weak spot: formal human writing is also
  predictable.
- **Burstiness** is about sentence shape, not words. So it can agree or disagree for a totally
  different reason.
- **Lexical tells** check surface vocabulary — cheap and sharp.
- **Punctuation** checks a different surface habit again.

One smart but paid signal (perplexity) plus three cheap, simple ones. A single signal is too
easy to fool, so the app never relies on just one.

**Note on perplexity:** Groq's chat API can't give raw token scores, so this signal asks a Groq
model to rate predictability from 0 to 1. If Groq is down, the signal abstains instead of
crashing.

---

## Confidence score & uncertainty — and why

The four scores become one **AI-likelihood** `P_ai` (0 to 1), returned as `confidence`.
**0.5 means total uncertainty.**

1. Drop any signal that abstained.
2. Take the weighted average of the rest → `M`.
3. Lower confidence when signals disagree:
   `disagreement = stdev(scores) / 0.5`, then `P_ai = 0.5 + (M − 0.5) · (1 − disagreement)`.
4. If fewer than 2 signals voted, force the result to "uncertain" (one signal isn't enough).

| `P_ai` | result |
|---|---|
| `≥ 0.70` | `likely_ai` |
| `0.30 – 0.70` | `uncertain` |
| `< 0.30` | `likely_human` |

**Why punish disagreement?** The whole point of using many signals is to check each other. A
plain average hides fights — two signals saying "AI" and two saying "human" average to 0.5,
which looks the same as four mild signals at 0.5. They are not the same. Measuring disagreement
keeps the score honest.

**Why standard deviation, not max − min?** Max − min only looks at the two extreme signals, so
one noisy signal could cancel three good ones. Standard deviation looks at the whole group, so a
single odd signal lowers confidence a bit instead of ruining it.

### Two examples (the score really changes)

**High confidence → `likely_ai`, 0.89**
> "Artificial intelligence represents a transformative paradigm shift in modern society. It is
> important to note that while the benefits are numerous, stakeholders must collaborate…"

perplexity 0.90, lexical 1.00 (both agree), burstiness and punctuation abstained → **0.89**.

**Lower confidence → `uncertain`, 0.51**
> "The relationship between monetary policy and asset price inflation has been extensively
> studied in the literature. Central banks face a fundamental tension…"

perplexity 0.90 (says AI) but lexical 0.00 (says human) → they disagree → the score drops from
0.60 to **0.51**. The app correctly avoids blaming a formal human writer.

So 0.89 and 0.51 give different labels — the score is meaningful, not a constant.

### What to change before real use

- Use real token-based perplexity from a dedicated model instead of asking a chat model.
- Learn the weights and thresholds from labeled data, and tune them per genre (poems vs prose).
- Refresh the AI phrase list often, since it goes stale.
- Use a real database, add login on `/log` and `/appeal`, and use Redis for rate limits.

---

## Transparency labels (three variants)

The label changes with the score: the variant flips at the thresholds, and the percentage
inside it moves. Exact text:

**Likely AI** (shows `P_ai`):
> 🤖 Likely AI-generated. Our analysis found strong signs this text was written by an AI tool
> (about 89% confidence). This is an automated estimate, not proof. If you wrote this yourself,
> you can appeal.

**Likely human** (shows `1 − P_ai`):
> ✍️ Likely human-written. Our analysis found strong signs this text was written by a person
> (about 82% confidence). This is an automated estimate, not proof.

**Uncertain** (shows `P_ai` as a lean):
> ❓ Uncertain. Our analysis couldn't confidently tell whether this text was written by a
> person or an AI (about 51% leaning AI). Please treat this result with caution.

The percentage comes from the real score. In the web UI these show as green / red / yellow boxes.

---

## Appeals

`POST /appeal` lets a creator contest a result. It changes the content's status to
**`under_review`**, logs the appeal next to the original decision in the audit log, and returns
a confirmation. No automatic re-classification — a human reviews it. `GET /review-queue` shows
everything waiting for review.

```bash
curl -s -X POST http://127.0.0.1:5000/appeal -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-ID", "creator_reasoning": "I wrote this myself..."}' \
  | ./.venv/bin/python -m json.tool
```

---

## Rate limiting

`/submit` is limited (per IP, in-memory) to **`10 per minute; 100 per day`**.

- **10/minute** — plenty for a real writer, but blocks a flooding script.
- **100/day** — caps abuse even if someone goes slowly.
- Each `/submit` makes a paid Groq call, so this also protects cost.

Proof (12 fast requests, limit 10/min):
```
request  1-10 -> 200
request 11    -> 429
request 12    -> 429
```
The 429 returns clean JSON: `{ "error": "Rate limit exceeded…", "limit": "10 per 1 minute" }`.

---

## Audit log

Every decision is saved to `audit_log.jsonl` as JSON Lines (one object per line, append-only).
Read it with `GET /log`. Each entry has the `timestamp`, `content_id`, `attribution`,
`confidence`, all four `signal_scores`, and the `label`. An appeal adds a second
`event:"appeal"` entry with `appeal_reasoning` and `status:"under_review"`. `llm_score` (raw
perplexity) is kept apart from `confidence` (the combined score).

Sample (3 decisions + 1 appeal):
```json
{
  "entries": [
    { "event": "classification", "content_id": "f6a9987f-…", "creator_id": "writer-1",
      "timestamp": "2026-06-28T23:45:05.935Z", "attribution": "likely_ai", "confidence": 0.89,
      "llm_score": 0.9,
      "signal_scores": { "perplexity": 0.9, "burstiness": 0.5, "lexical": 1.0, "punctuation": 0.5 },
      "signals_used": ["lexical", "perplexity"], "weighted_mean": 0.933, "disagreement": 0.1,
      "label": "🤖 Likely AI-generated. … (about 89% confidence). …", "status": "classified" },
    { "event": "classification", "content_id": "b0e26c15-…", "creator_id": "writer-2",
      "timestamp": "2026-06-28T23:45:06.271Z", "attribution": "likely_human", "confidence": 0.175,
      "llm_score": 0.2,
      "signal_scores": { "perplexity": 0.2, "burstiness": 0.0, "lexical": 0.0, "punctuation": 0.5 },
      "signals_used": ["burstiness", "lexical", "perplexity"], "weighted_mean": 0.1, "disagreement": 0.189,
      "label": "✍️ Likely human-written. … (about 82% confidence). …", "status": "classified" },
    { "event": "classification", "content_id": "d353e8e6-…", "creator_id": "writer-3",
      "timestamp": "2026-06-28T23:45:07.500Z", "attribution": "uncertain", "confidence": 0.51,
      "llm_score": 0.9,
      "signal_scores": { "perplexity": 0.9, "burstiness": 0.5, "lexical": 0.0, "punctuation": 0.5 },
      "signals_used": ["lexical", "perplexity"], "weighted_mean": 0.6, "disagreement": 0.9,
      "label": "❓ Uncertain. … (about 51% leaning AI). …", "status": "classified" },
    { "event": "appeal", "content_id": "b0e26c15-…", "appeal_id": "587b21fa-…",
      "creator_id": "writer-2", "timestamp": "2026-06-28T23:45:07.520Z", "status": "under_review",
      "appeal_reasoning": "I wrote this myself from personal experience. English is my second language…",
      "original_attribution": "likely_human", "original_confidence": 0.175 }
  ]
}
```

---

## Known limitations

**Short, simple poems are the clearest failure.** A haiku or a repetition-heavy poem with
short, even lines will probably be misread as AI. This comes straight from how two signals work:

- **Burstiness** measures how much sentence length changes. A human poem with even short lines
  looks exactly like AI's even lines — so burstiness can't tell careful human style from machine
  uniformity.
- **Perplexity** treats predictable text as AI, and simple poems are predictable.

When both fire, a real human poem can score as AI. The wide "uncertain" band, burstiness
abstaining on short text, and the appeal option help, but don't fully fix it.

Other weak spots: formal human writing (academic, legal) can look like AI to perplexity; the
phrase list and Groq model only work well in English; and very short text leaves only 1–2
signals voting.

---

## Spec reflection

**How the spec helped:** writing the full plan first (signals, formula, thresholds, API) gave
each step a clear target. The scoring part especially — the formula was written before the code,
so the code could be checked against it, and any mismatch showed up fast.

**How the code diverged:** the plan said disagreement = `max − min`. In testing, that let one
odd signal cancel three good ones, so a clearly-AI text dropped to "uncertain." The code was
changed to use **standard deviation** instead, and `planning.md` was updated to match. (Smaller
change: the perplexity signal became an LLM rating instead of true token perplexity, because
Groq's API doesn't expose token scores.)

---

## AI usage

This project was built with an AI coding assistant. Some specific cases:

1. **Scoring logic.** I asked the AI to build the scorer from the plan. It used a weighted
   average with a `max − min` penalty. Testing showed clear cases collapsing to "uncertain," so
   I overrode it: switched to standard deviation, let signals abstain so a neutral 0.5 doesn't
   vote, and added a guard for single-signal cases.

2. **Punctuation signal.** I asked for a punctuation signal. Its first version treated "no
   em-dashes" as proof of a human, so an AI paragraph scored 0.21 (wrong). I changed it to only
   look for AI habits and abstain when it finds none.

3. **Burstiness.** The AI set a 2-sentence minimum. A 3-sentence AI text gave a noisy result
   that dragged the verdict down, so I raised the minimum to 4 sentences.

In each case the first version looked fine but behaved wrong, and testing on real inputs caught it.

---

## API reference

| Method & path | Purpose |
|---|---|
| `POST /submit` | Classify text. Body: `{ "text", "creator_id"? }`. Rate-limited. |
| `POST /appeal` | Contest a result. Body: `{ "content_id", "creator_reasoning" }`. |
| `GET /log` | Audit log entries. Filters: `?content_id=`, `?limit=`. |
| `GET /review-queue` | Content waiting for review. |
| `GET /content/<id>` | One content record. |
| `GET /health` | Liveness check. |

## Files

| File | Role |
|---|---|
| `app.py` | Flask app, routes, rate limiting |
| `ui.py` | Streamlit web UI (calls the API) |
| `signals.py` | The four signals |
| `scoring.py` | Combines scores → confidence + result |
| `labels.py` | The three label texts |
| `audit.py` | Append-only audit log |
| `store.py` | Content store (survives restart) |
| `planning.md` | Design doc |
| `test.sh` | Test suite |
