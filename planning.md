# Provenance Guard — Planning

A service that guesses whether text was written by a human or an AI. It gives a
confidence score, shows a plain-English label, and lets creators appeal.

---

## 1. Detection Signals

For each: what it looks at, why human and AI text differ, where it gets fooled, and what
its **output** is. Every signal returns a single **score from 0 to 1** (0 = looks human,
1 = looks AI).

### Signal 1 — Perplexity / predictability (uses Groq)

- **Looks at:** how _predictable_ the words are. Low = every word is the obvious choice.
- **Why they differ:** AI picks the most likely next word, so its text is smooth and
  predictable. Humans pick surprising words, so their text is bumpier.
- **How we get it:** we send the text to a Groq model and ask it to rate, 0–1, how
  predictable/formulaic the writing reads (an LLM-judge that approximates perplexity).
- **Gets fooled by:** formal or boring human writing (also very predictable) → looks AI.
  Edited or creative AI → looks human. Bad on very short text.
- **Output:** `0–1` score.

### Signal 2 — Burstiness

- **Looks at:** how much sentence length changes. High = long sentence, then a short one.
- **Why they differ:** humans mix long and short sentences. AI keeps them all about the
  same length.
- **How we get it:** split into sentences, compute the spread of sentence lengths
  (std ÷ mean = "coefficient of variation"). Low spread → high AI score.
- **Gets fooled by:** poems, lists, and technical docs (all even lengths) → look AI.
- **Output:** `0–1` score.

### Signal 3 — Lexical tells

- **Looks at:** how often AI-favorite words show up — "delve," "tapestry," "it's important
  to note," "in today's fast-paced world."
- **Why they differ:** AI overuses these polished phrases. Humans use them less often.
- **How we get it:** count hits from a phrase list, per 100 words; more hits → higher score.
- **Gets fooled by:** the word list gets old; polished human writers use these words too;
  easy to dodge with find-and-replace.
- **Output:** `0–1` score.

### Signal 4 — Punctuation

- **Looks at:** how punctuation is used — em-dashes, comma rhythm, neat balanced lists.
- **Why they differ:** AI punctuates very neatly and evenly. Humans are messier.
- **How we get it:** measure em-dash rate and how even the comma/list pattern is.
- **Gets fooled by:** carefully edited human writing (also neat); AI told to "write casually."
- **Output:** `0–1` score.

### How we combine them into one score

1. **Weighted average.** Perplexity is the strongest, so it counts most:
   `M = 0.40·perplexity + 0.20·burstiness + 0.20·lexical + 0.20·punctuation`.
2. **Punish disagreement.** Take the spread `= max(score) − min(score)` and pull the result
   toward the middle when signals disagree:
   `P_ai = 0.5 + (M − 0.5) · (1 − spread)`.
   - If all four agree (spread ≈ 0) → `P_ai = M`.
   - If they fully disagree (spread ≈ 1) → `P_ai ≈ 0.5` (uncertain).

`P_ai` (0–1) is our final **AI-likelihood** and the number we return as `confidence`.

---

## 2. Uncertainty & Calibration

**What the number means.** `P_ai` is "how likely this is AI," from 0 to 1. **0.5 means a
coin flip — maximum uncertainty.** So **0.6 means the signals lean slightly toward AI but
not enough to call it** — it lands in the Uncertain band below.

**Thresholds (one axis, three bands):**
| `P_ai` | Result |
|---|---|
| `≥ 0.70` | **AI** |
| `0.30 – 0.70` | **Uncertain** |
| `< 0.30` | **Human** |

The Uncertain band is wide on purpose so genre quirks (poems, lists) fall into "uncertain"
instead of a false accusation.

**Mapping raw signals to a calibrated score.** Each signal is normalized to 0–1 before
fusion:

- **Perplexity (Groq):** the model returns 0–1 directly; we anchor the prompt with examples
  so its scale is stable.
- **Burstiness:** `score = clamp(1 − CV/0.6, 0, 1)` (CV = coefficient of variation). Human
  prose averages CV ≈ 0.5; AI ≈ 0.2.
- **Lexical:** `score = min(1, hits_per_100_words / 3)` (3+ tells per 100 words = full AI).
- **Punctuation:** combine em-dash rate and list-evenness into 0–1.

**How we'll test the scores are meaningful (README).** Build a tiny labeled set — known
human texts (classic poems, personal blog posts) and known AI texts (Groq/ChatGPT outputs).
Check that AI texts score `P_ai` high, human texts score low, and **edited/mixed texts land
in the Uncertain band**. If a 0.51 and a 0.95 produced the same label, the scoring is broken.

---

## 3. Transparency Labels (exact text)

The API returns `confidence` as `P_ai`. The label shows a reader-friendly percentage for the
verdict it displays (AI → `P_ai`; Human → `1 − P_ai`).

**High-confidence AI** (`P_ai ≥ 0.70`):

> 🤖 **Likely AI-generated.** Our analysis found strong signs this text was written by an AI
> tool (about 87% confidence). This is an automated estimate, not proof. If you wrote this
> yourself, you can appeal.

**High-confidence human** (`P_ai < 0.30`):

> ✍️ **Likely human-written.** Our analysis found strong signs this text was written by a
> person (about 91% confidence). This is an automated estimate, not proof.

**Uncertain** (`0.30 ≤ P_ai < 0.70`):

> ❓ **Uncertain.** Our analysis couldn't confidently tell whether this text was written by a
> person or an AI (about 55% leaning AI). Please treat this result with caution.

(The percentages are examples; the real number comes from `P_ai`.)

---

## 4. Appeals Workflow

- **Who can appeal:** the creator of the content. They identify the item with its
  `content_id` (returned at submission). No login system in this project, so anyone holding
  the `content_id` can appeal; we record `creator_id` if it was given.
- **What they provide:** the `content_id` and their **reasoning** (free text, required) —
  e.g. "I wrote this poem myself, here's my draft history."
- **What the system does on appeal:**
  1. Look up the content. If it doesn't exist → `404`.
  2. Create an appeal record (`appeal_id`, `content_id`, reasoning, timestamp).
  3. Attach the appeal to that content's audit-log entry (next to the original decision).
  4. Change the content's status from `classified` → `under_review`.
  5. Return a confirmation (`status`, `appeal_id`).
  - **No automatic re-classification** — a human decides later.
- **What a reviewer sees in the queue:** a list of all `under_review` items, each showing the
  original text, the result + `P_ai`, the **four signal scores**, the label that was shown,
  the creator's reasoning, and timestamps — everything needed to make a human call.

---

## 5. Anticipated Edge Cases

Specific cases our heuristics handle poorly:

1. **Minimalist poetry (short lines, repetition, simple words).** A haiku or a repetition-
   heavy poem has even line lengths (burstiness → AI), simple predictable words (perplexity →
   AI), and clean punctuation (→ AI), so a real human poem can score as AI. _Mitigation:_ wide
   Uncertain band + a minimum-length guard so tiny texts aren't judged confidently.
2. **Grammarly-polished human essay.** A person's formal essay run through a grammar tool has
   clean punctuation and a smooth, predictable style — exactly the AI fingerprint — so it can
   be a false "AI." _Mitigation:_ this is why appeals exist; the signal disagreement often
   still pulls it toward Uncertain.
3. **Non-English or code-mixed text.** The Groq model and the English-only phrase list are
   unreliable here, inflating perplexity and missing tells. _Mitigation:_ flag short/unknown-
   language inputs and lean Uncertain.

---

## 6. The False-Positive Problem (worked trace)

A human poet submits a tidy poem with even short lines and clean punctuation.

- **Perplexity (Groq):** surprising imagery → `0.2` (human).
- **Burstiness:** even lines → `0.7` (AI).
- **Lexical tells:** a polished phrase → `0.6` (AI).
- **Punctuation:** clean → `0.6` (AI).

`M = 0.40·0.2 + 0.20·0.7 + 0.20·0.6 + 0.20·0.6 = 0.46`. `spread = 0.7 − 0.2 = 0.5`.
`P_ai = 0.5 + (0.46 − 0.5)·(1 − 0.5) = 0.48` → **Uncertain**, not "AI." The disagreement
protected the poet. The label is soft; if they still disagree they file an appeal and the
status becomes `under_review`.

**Rule:** disagreement → low confidence → soft label → easy appeal. The system leans toward
"uncertain" instead of accusing.

---

## 7. API Surface (the contract)

### `POST /submit` — send text for a verdict

**Accepts**

```json
{ "text": "string (required)", "creator_id": "string (optional)" }
```

**Returns `200`**

```json
{
	"content_id": "uuid",
	"result": "AI | Human | Uncertain",
	"confidence": 0.87,
	"label": "plain-English text shown to the reader",
	"signals": {
		"perplexity": { "score": 0.12, "note": "very predictable" },
		"burstiness": { "score": 0.4, "note": "fairly even sentences" },
		"lexical": { "score": 0.1, "note": "1 AI phrase found" },
		"punctuation": { "score": 0.2, "note": "regular commas" }
	},
	"status": "classified",
	"timestamp": "ISO-8601"
}
```

**Errors:** `400` (no text / too short / too long), `429` (rate limited).

### `POST /appeal` — contest a verdict

**Accepts**

```json
{ "content_id": "uuid (required)", "creator_reasoning": "string (required)" }
```

**Returns `200`**

```json
{
	"content_id": "uuid",
	"appeal_id": "uuid",
	"status": "under_review",
	"logged_at": "ISO-8601"
}
```

**Errors:** `404` (unknown content_id), `400` (no reasoning).

### `GET /log` — read the audit log

**Accepts (query):** `?content_id=` and `?limit=` (both optional).
**Returns `200`:** a list of entries, each with the decision, confidence, signal scores,
label shown, and any appeals.

### `GET /content/{id}` — check status _(optional)_

**Returns:** `{ content_id, result, confidence, status, timestamp }`.

### `GET /health` — is it alive _(optional)_

**Returns:** `{ "status": "ok" }`.

---

## 8. Architecture

### Submission flow

```
Client
  | raw text + creator_id
  v
POST /submit
  | who is asking
  v
Rate Limiter ----------(429 if over limit)----------> Client
  | raw text
  v
Input Validation ------(400 if invalid)------------> Client
  | clean text
  v
Detection Pipeline
  |            |             |              |
  v            v             v              v
Perplexity  Burstiness    Lexical       Punctuation
 (Groq)        |             |              |
  \            |  score 0-1  |             /
   \           |             |            /
    v          v             v           v
            Confidence Scorer  ->  P_ai (0-1) + result
                 |
                 | result + confidence
                 v
            Label Generator
                 | result + confidence + label text
                 v
            Audit Logger ----(save decision)----> Storage
                 | JSON response
                 v
               Client
```

### Appeal flow

```
Creator
  | content_id + reasoning
  v
POST /appeal
  | find content_id
  v
Storage --------(404 if not found)--------> Creator
  |
  v
Audit Logger ----(attach appeal to decision)----> Storage
  | set status = under_review
  v
Storage
  | confirm: status + appeal_id
  v
Creator
```

**Narrative.** _Submission:_ text comes in through `POST /submit`, passes the rate limiter and
validation, then the detection pipeline runs all four signals (perplexity via Groq, the rest
local). The confidence scorer fuses them into `P_ai`, the label generator turns that into a
plain-English label, and the audit logger saves the whole decision before the JSON response
goes back. _Appeal:_ a creator sends `content_id` + reasoning to `POST /appeal`; the system
finds the content, attaches the appeal to its audit entry, flips its status to `under_review`,
and confirms — a human reviews it later (no auto re-classification).

---

## 9. AI Tool Plan

How we'll use an AI coding tool across the three build milestones — what spec we feed it,
what we ask it to write, and how we check the output before trusting it.

### M3 — Submission endpoint + first signal
- **Spec we provide:** §1 Detection Signals (focus on Signal 1, perplexity/Groq) and the
  §8 Architecture diagram, plus the `POST /submit` contract from §7.
- **What we ask it to generate:** a Flask app skeleton with the `POST /submit` route, request
  parsing/validation, and the **first signal function** (`perplexity_score(text) → 0–1` that
  calls Groq).
- **How we verify:** call `perplexity_score()` directly on a few hand-picked inputs (a known
  AI paragraph, a messy human paragraph, a one-line string) and confirm the scores look
  sensible **before** wiring it into the endpoint. Then hit `/submit` with curl and check the
  JSON shape matches the contract.

### M4 — Second signal + confidence scoring
- **Spec we provide:** §1 Detection Signals (Signal 2 + the fusion formula), §2 Uncertainty &
  Calibration (thresholds + normalization), and the §8 diagram.
- **What we ask it to generate:** the **second signal function** (`burstiness_score(text) →
  0–1`) and the **scoring logic** — the weighted average, the disagreement penalty
  (`P_ai = 0.5 + (M − 0.5)·(1 − spread)`), and the threshold → result mapping.
- **What we check:** run clearly-AI text and clearly-human text through the combined scorer
  and confirm scores **vary meaningfully** (AI lands high, human lands low). Feed an edited/
  mixed text and confirm it lands in the Uncertain band. Confirm a 0.51 and a 0.95 don't
  collapse to the same result.

### M5 — Production layer (labels + appeals + the rest)
- **Spec we provide:** §3 Transparency Labels (the three exact variants), §4 Appeals Workflow,
  and the §8 appeal-flow diagram, plus the `POST /appeal` and `GET /log` contracts from §7.
- **What we ask it to generate:** the **label generation logic** (`P_ai` → one of the three
  label texts) and the **`POST /appeal` endpoint** (look up content, log the appeal next to
  the decision, flip status to `under_review`), plus the audit log and rate limiter.
- **How we verify:** craft inputs that land in each band so **all three label variants are
  reachable** (high AI, high human, uncertain). Submit a piece, appeal it, and confirm the
  status changes to `under_review` and the appeal shows up in `GET /log` next to the original
  decision.

---

## Locked decisions

- **Fusion:** weighted average, then pulled toward 0.5 by signal disagreement.
- **Thresholds:** AI `≥0.70`, Uncertain `0.30–0.70`, Human `<0.30`.
- **Storage:** start with in-memory dicts; upgrade to a JSON file / SQLite if time allows.
- **Rate limit:** chosen value + window to be finalized and justified in the README.

```

```
