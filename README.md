# Provenance Guard

A content-attribution service. You submit a piece of text (a poem, a story excerpt, a blog
post); it estimates whether the text was written by a **human** or an **AI**, returns an
honest **confidence score**, shows a plain-English **transparency label**, lets creators
**appeal**, and records every decision in a structured **audit log**.

Detection uses **four independent signals** fused into a single score, with a disagreement
penalty so the system says "uncertain" instead of confidently accusing when its signals
conflict. See [planning.md](planning.md) for the full design and architecture diagrams.

---

## ⚠️ Important: use `127.0.0.1`, not `localhost` (port 5000 on macOS)

On macOS, **AirPlay Receiver** (the `ControlCe` process) listens on port **5000** over IPv6,
which is what `localhost` resolves to first. Our app binds IPv4 `127.0.0.1:5000`. As a result:

- `http://127.0.0.1:5000` → **the app** ✅
- `http://localhost:5000` → **AirPlay**, returns `403` ❌

**Always use `http://127.0.0.1:5000`** in curl commands and tests. (Alternatively, disable
*System Settings → General → AirDrop & Handoff → AirPlay Receiver*, which frees `localhost:5000`.)

---

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
echo "GROQ_API_KEY=your_key_here" > .env      # required for the perplexity signal
```

## Run

```bash
./.venv/bin/python app.py        # serves on http://127.0.0.1:5000
```

## Test

```bash
./test.sh            # starts the server, runs a suite of requests, stops it
./test.sh signal     # runs the signal functions directly (no server)
```

---

## Detection signals (multi-signal pipeline)

Each signal takes text and returns a score in `[0, 1]` (0 = looks human, 1 = looks AI), or
**abstains** when it has nothing reliable to measure. We use four because each fails in a
*different* way — where one is blind, another can still see.

| Signal | What it captures | Why we chose it |
|---|---|---|
| **Perplexity** (Groq) | Statistical predictability — how "smooth/formulaic" the wording is | Catches AI even when vocabulary looks human; strongest signal, so weighted highest |
| **Burstiness** | Variance in sentence length (rhythm) | Structural, independent of vocabulary — humans mix long/short, AI is uniform |
| **Lexical tells** | Density of AI-overused phrases ("delve", "tapestry", "it's important to note") | Cheap, sharp, catches the recognizable AI register |
| **Punctuation** | AI punctuation tells (em-dashes, rule-of-three lists, regular comma spacing) | A different surface fingerprint; detector-style (only argues "AI" or abstains) |

Weights: **perplexity 0.40, burstiness 0.20, lexical 0.20, punctuation 0.20.** Full
descriptions, blind spots, and rationale are in [planning.md §1](planning.md).

### Signal 1 implementation note (Groq)
Groq serves chat models, not raw token-logprobs, so the perplexity signal is implemented as an
**LLM-judge**: we prompt a Groq model (default `llama-3.3-70b-versatile`) with an anchored
0–1 scale to rate predictability, and parse a structured JSON reply. If Groq is unavailable,
the signal **abstains** (degrades gracefully) rather than crashing the request.

---

## Confidence scoring & uncertainty

We combine the signals into one **AI-likelihood** `P_ai ∈ [0,1]`, reported as `confidence`.
**0.5 = maximum uncertainty** (a coin flip).

1. **Drop abstentions.** A signal that had nothing to measure (`available: false`) does not
   vote — a "no information" signal must not act like a real one.
2. **Weighted average** of the voting signals → `M`.
3. **Disagreement penalty.** Disagreement = standard deviation of the voting scores,
   normalized by its max (0.5). Then `P_ai = 0.5 + (M − 0.5) · (1 − disagreement)`.
   - Signals agree → little penalty → confident verdict.
   - Signals split → `P_ai` collapses toward 0.5 → "uncertain".
   - We use **standard deviation, not max−min**, so one noisy outlier can't veto three
     agreeing signals (max−min can't tell 3-vs-1 from 2-vs-2; std can).
4. **Lone-signal guard.** If fewer than 2 signals vote, the result is forced into the
   uncertain band — a single signal can't be corroborated, so we never report high confidence
   from it.

### Thresholds → attribution

| `P_ai` (confidence) | attribution |
|---|---|
| `≥ 0.70` | `likely_ai` |
| `0.30 – 0.70` | `uncertain` |
| `< 0.30` | `likely_human` |

### How we tested the scores are meaningful

We ran labeled inputs (clearly AI, clearly human, two borderline) and checked each landed
where intuition says, printing per-signal scores to find any misbehaving signal:

| Input | confidence | result |
|---|---|---|
| Clearly AI (buzzword paragraph) | **0.89** | `likely_ai` |
| Clearly human (casual review) | **0.175** | `likely_human` |
| Borderline: formal human | **0.51** | `uncertain` |
| Borderline: lightly edited AI | **0.509** | `uncertain` |

A 0.51 and a 0.95 produce different labels (and different displayed percentages), confirming
the score is meaningful rather than binary. During this testing we also found and fixed real
calibration bugs (e.g. burstiness voting on too few sentences, a confidence/label boundary
mismatch, single-signal overconfidence) — see the commit history and [planning.md §2](planning.md).

---

## Transparency labels (three variants)

The label returned by `/submit` changes with the score in two ways: the **variant** flips at
the thresholds, and the **percentage** inside it moves with the confidence. Exact text:

**High-confidence AI** (`attribution = likely_ai`, shows `P_ai`):
> 🤖 Likely AI-generated. Our analysis found strong signs this text was written by an AI tool
> (about 89% confidence). This is an automated estimate, not proof. If you wrote this yourself,
> you can appeal.

**High-confidence human** (`attribution = likely_human`, shows `1 − P_ai`):
> ✍️ Likely human-written. Our analysis found strong signs this text was written by a person
> (about 82% confidence). This is an automated estimate, not proof.

**Uncertain** (`attribution = uncertain`, shows `P_ai` as a lean):
> ❓ Uncertain. Our analysis couldn't confidently tell whether this text was written by a
> person or an AI (about 51% leaning AI). Please treat this result with caution.

The percentage is filled from the actual score, so e.g. a 0.95 AI verdict reads "about 95%
confidence" while a 0.72 reads "about 72% confidence."

---

## Appeals workflow

`POST /appeal` lets a creator contest a classification. It:
1. updates the content's status to **`under_review`** in the content store,
2. logs the appeal **alongside the original decision** in the audit log (an `event: "appeal"`
   entry carrying `appeal_reasoning` and the original verdict), and
3. returns a confirmation (`appeal_id`, `status`).

No automated re-classification — a human reviews it. `GET /review-queue` shows everything
awaiting review (original text, verdict, and the creator's reasoning).

```bash
curl -s -X POST http://127.0.0.1:5000/appeal -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-ID", "creator_reasoning": "I wrote this myself..."}' \
  | ./.venv/bin/python -m json.tool
```

---

## Rate limiting

Applied to `/submit` with **Flask-Limiter** (per client IP, in-memory storage):

```
10 per minute; 100 per day
```

**Reasoning (defensible, not arbitrary):**
- **10/minute** — a real writer checking their own work submits a handful of pieces in a
  sitting; 10/min is comfortably above genuine use, but a flooding script blows past it at once.
- **100/day** — caps sustained abuse even if someone paces under the per-minute limit.
- **Cost protection** — every `/submit` makes a *paid Groq API call*, so this also guards the
  budget, not just server load.

**Evidence** (12 rapid requests; limit is 10/min):
```
request  1-10 -> 200
request 11    -> 429
request 12    -> 429
```
The `429` returns clean JSON:
```json
{ "error": "Rate limit exceeded. Please slow down and try again later.", "limit": "10 per 1 minute" }
```

---

## Audit log

Every decision is written to `audit_log.jsonl` as **structured JSON Lines** (one object per
line — append-only, never rewritten). Read it back with `GET /log` (returns `{"entries": [...]}`).
Each entry captures: `timestamp`, `content_id`, `attribution`, `confidence`, every individual
`signal_scores` value, the `label` shown, and — for appeals — a separate `event: "appeal"`
entry with `appeal_reasoning` and `status: "under_review"`.

Sample (`GET /log`, 3 classifications + 1 appeal):

```json
{
  "entries": [
    {
      "event": "classification", "content_id": "f6a9987f-…", "creator_id": "writer-1",
      "timestamp": "2026-06-28T23:45:05.935Z",
      "attribution": "likely_ai", "confidence": 0.89, "llm_score": 0.9,
      "signal_scores": { "perplexity": 0.9, "burstiness": 0.5, "lexical": 1.0, "punctuation": 0.5 },
      "signals_used": ["lexical", "perplexity"],
      "weighted_mean": 0.933, "disagreement": 0.1,
      "label": "🤖 Likely AI-generated. … (about 89% confidence). …",
      "status": "classified"
    },
    {
      "event": "classification", "content_id": "b0e26c15-…", "creator_id": "writer-2",
      "timestamp": "2026-06-28T23:45:06.271Z",
      "attribution": "likely_human", "confidence": 0.175, "llm_score": 0.2,
      "signal_scores": { "perplexity": 0.2, "burstiness": 0.0, "lexical": 0.0, "punctuation": 0.5 },
      "signals_used": ["burstiness", "lexical", "perplexity"],
      "weighted_mean": 0.1, "disagreement": 0.189,
      "label": "✍️ Likely human-written. … (about 82% confidence). …",
      "status": "classified"
    },
    {
      "event": "classification", "content_id": "d353e8e6-…", "creator_id": "writer-3",
      "timestamp": "2026-06-28T23:45:07.500Z",
      "attribution": "uncertain", "confidence": 0.51, "llm_score": 0.9,
      "signal_scores": { "perplexity": 0.9, "burstiness": 0.5, "lexical": 0.0, "punctuation": 0.5 },
      "signals_used": ["lexical", "perplexity"],
      "weighted_mean": 0.6, "disagreement": 0.9,
      "label": "❓ Uncertain. … (about 51% leaning AI). …",
      "status": "classified"
    },
    {
      "event": "appeal", "content_id": "b0e26c15-…", "appeal_id": "587b21fa-…",
      "creator_id": "writer-2", "timestamp": "2026-06-28T23:45:07.520Z",
      "status": "under_review",
      "appeal_reasoning": "I wrote this myself from personal experience. English is my second language…",
      "original_attribution": "likely_human", "original_confidence": 0.175
    }
  ]
}
```

`llm_score` (raw perplexity) is kept separate from `confidence` (fused) so you can always see
what Groq alone said versus the combined verdict.

---

## API reference

| Method & path | Purpose |
|---|---|
| `POST /submit` | Classify text. Body: `{ "text", "creator_id"? }`. Returns attribution, confidence, label, per-signal breakdown. Rate-limited. |
| `POST /appeal` | Contest a verdict. Body: `{ "content_id", "creator_reasoning" }`. Sets status `under_review`. |
| `GET /log` | Audit log entries: `{ "entries": [...] }`. Filters: `?content_id=`, `?limit=`. |
| `GET /review-queue` | Content currently `under_review` (reviewer view). |
| `GET /content/<id>` | Current state of one content record. |
| `GET /health` | Liveness check. |

## Project layout

| File | Role |
|---|---|
| `app.py` | Flask app, routes, rate limiting |
| `signals.py` | The four detection signals |
| `scoring.py` | Fusion → confidence + attribution |
| `labels.py` | Transparency label text (3 variants) |
| `audit.py` | Append-only audit log (JSONL) |
| `store.py` | Mutable content store (JSON, survives restart) |
| `planning.md` | Design doc: signals, uncertainty, labels, appeals, edge cases, architecture |
| `test.sh` | Smoke-test suite |
