# AI Interviewer — Technical Deep Dive

*Interview-ready documentation. Written for a human to explain, not a machine to generate.*

---

## Table of Contents

1. [What This Thing Does](#1-what-this-thing-does)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Frontend](#3-frontend)
4. [Backend & API Layer](#4-backend--api-layer)
5. [Orchestration — How the Pipeline Works](#5-orchestration--how-the-pipeline-works)
6. [The Four Agents (and what they really are)](#6-the-four-agents-and-what-they-really-are)
7. [Prompt Engineering](#7-prompt-engineering)
8. [Scoring & Evaluation System](#8-scoring--evaluation-system)
9. [Grill Mode](#9-grill-mode)
10. [State Management](#10-state-management)
11. [Voice Layer](#11-voice-layer)
12. [Tech Stack](#12-tech-stack)
13. [Design Decisions & Trade-offs](#13-design-decisions--trade-offs)
14. [True Agent vs. Prompted LLM — Honest Answer](#14-true-agent-vs-prompted-llm--honest-answer)
15. [Possible Interview Questions + Strong Answers](#15-possible-interview-questions--strong-answers)

---

## 1. What This Thing Does

It's a mock interview system that behaves like a real interviewer.

You tell it: what role you're practicing for, your background, the topics to cover, and the difficulty level. It then runs a full interview — asks an opening question, listens to your answers, decides what to ask next based on what you actually said, and at the end produces a detailed performance report with scores, transcript evidence, and specific practice recommendations.

**The two things that make it different from a static Q&A bot:**

1. It actually reads your answer before deciding the next question. If you mention a specific technical decision, it may probe that decision. If you give a vague answer, it asks for specifics. If you're clearly struggling, it moves on rather than piling on.

2. The final report is grounded in the transcript. Every strength, weakness, and recommendation references specific turns with paraphrased quotes — it doesn't produce generic "communicate more clearly" advice.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────┐
│                   FRONTEND                       │
│         React SPA (Vite) — Netlify               │
│                                                  │
│  SetupScreen → InterviewScreen → ReportScreen    │
│  Voice: Web Speech API (STT) + ElevenLabs (TTS)  │
└──────────────────┬──────────────────────────────┘
                   │  HTTP REST (3 endpoints)
┌──────────────────▼──────────────────────────────┐
│                   BACKEND                        │
│         FastAPI — Render.com                     │
│                                                  │
│  POST /session/start                             │
│  POST /session/answer                            │
│  GET  /session/report                            │
│  POST /voice/speak  (ElevenLabs proxy)           │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│            LANGGRAPH PIPELINE                    │
│                                                  │
│  init → interviewer → [human_input] →            │
│  evaluator → derive_signals → strategy →         │
│  append_turn → (loop back OR coach)              │
└──────────────────┬──────────────────────────────┘
                   │  4 separate LLM calls per turn
┌──────────────────▼──────────────────────────────┐
│         GEMINI FLASH LITE (all 4 agents)         │
│                                                  │
│  Interviewer Agent   — generates questions       │
│  Evaluator Agent     — scores answers            │
│  Strategy Agent      — decides what happens next │
│  Coach/Report Agent  — generates final report    │
└─────────────────────────────────────────────────┘
```

**End-to-end interview lifecycle:**

```
User fills setup form
        ↓
POST /session/start
  → Creates ImmutableContext (session config, frozen for the interview)
  → LangGraph runs: init → interviewer (opening question)
  → LangGraph pauses at human_input node (awaits user answer)
        ↓
Backend returns: session_id + first question
        ↓
User speaks/types answer
        ↓
POST /session/answer
  → LangGraph resumes: human_input captured
  → Evaluator scores the answer (4 dimensions, 8 flags)
  → DerivedSignals computed (coverage%, trajectory, difficulty)
  → Strategy decides next action (probe / follow_up / pivot / wrap_up)
  → Guardrails check and potentially override the decision
  → AppendTurn records the full TurnRecord
  → Route: if wrapping up → Interviewer generates closing
           if done → Coach generates report → pipeline ends
  → Otherwise: Interviewer generates next question → pause again
        ↓
[Repeat per turn]
        ↓
GET /session/report
  → Coach report retrieved from in-memory state
  → Transcript attached to response
```

---

## 3. Frontend

### Framework and structure

**React with Vite.** Single file: `frontend/src/App.jsx`. All styles are written as a template literal string (`const STYLES = \`...\``) injected as a `<style>` tag — no CSS modules, no Tailwind, no separate stylesheet. This was a deliberate choice to keep everything self-contained and easy to deploy. Deployed on Netlify.

There's no router (no React Router). The app has five visual "phases" managed by a single `phase` state variable:

```js
const [phase, setPhase] = useState('setup')
// 'setup' | 'interview' | 'report' | 'report-shared' | 'insufficient'
```

Each phase renders a different full-screen component. Navigation is purely state transitions. On mount, the app checks `window.location.search` for a `?report_id=xxx` parameter — if present, it starts in `report-shared` phase and loads that report directly via `GET /report/{report_id}`, bypassing the session entirely.

### Components

| Component | What it does |
|---|---|
| `SetupScreen` | Form: role, focus area, topics, difficulty, interviewer persona, interview mode |
| `InterviewScreen` | Chat UI: mic button, transcript box, send button, header badges |
| `ReportScreen` | Report: score bars, feedback cards, topic coverage, practice recommendations, transcript. Has Download PDF, Share Report, and New Interview buttons. Handles both normal (sessionId) and shared (reportId) load modes. |
| `EndInterviewModal` | Confirmation dialog for ending the interview early |
| `InsufficientDataScreen` | Shown when early termination is below the turn threshold |
| `ScoreBar` | A single score dimension with label + bar |
| `FeedbackCard` | One feedback point: observation + evidence chips + suggestion |
| `Citation` | A clickable "Turn N" chip that jumps to that turn in the transcript |
| `Transcript` | Collapsible full Q&A log, with highlight-on-cite behavior |

### State management

No Redux, no Zustand. Just `useState` and `useRef`. State lives in three places:

1. `SetupScreen` local state — form inputs (discarded after submit)
2. `App` level `session` object — holds session_id, first question, role, interview_mode
3. `InterviewScreen` local state — messages array, loading flag, current topic/phase/turn count
4. `ReportScreen` local state — fetches and stores the report once

The `session` object is the only thing passed between screens. It's minimal on purpose — the backend is the source of truth.

### API communication

One file: `frontend/src/api/client.js`. Seven methods: `startSession()`, `submitAnswer()`, `getReport()`, `getReportById()`, `endSession()`, `downloadPdf()`, `downloadPdfById()`. All plain `fetch`. The base URL is read from `import.meta.env.VITE_API_URL`.

No WebSockets. Each answer is a regular HTTP POST. This is stateless from the transport layer's perspective — the session state lives on the backend.

**PDF download flow:** `downloadPdf(sessionId)` fetches `GET /session/report/pdf`, receives raw bytes, creates an object URL via `URL.createObjectURL(blob)`, programmatically clicks a link, then revokes the object URL. No server-side file storage — the PDF is generated on the fly and streamed.

**Share link flow:** After the report loads, the response includes a `report_id`. The "Share report" button copies `window.location.origin + ?report_id={id}` to clipboard via `navigator.clipboard.writeText()` (with a `document.execCommand('copy')` fallback). Anyone with that URL can open the report directly from the backend's in-memory store.

### Voice handling

Two separate systems, both in `App.jsx` as custom hooks:

**Speech-to-text (`useSpeechToText`):** Uses the browser's native Web Speech API (`window.SpeechRecognition`). No external service. Works in Chrome/Edge, not in Firefox/Safari. Streams interim results live into the textarea as the user speaks. On stop, cleans up the `[listening...]` suffix. Fully free, no API keys.

**Text-to-speech (`useElevenLabs`):** Calls `POST /voice/speak` on the backend, which proxies to ElevenLabs using a server-side API key. Returns raw `audio/mpeg` bytes. Frontend creates a Blob URL and plays it with `new Audio(url)`. If the server returns 503 (no key configured), voice degrades silently — `voiceAvailableRef` is set false and no more calls are made. API key is never sent to the client.

### Why React?

Familiarity and iteration speed. The report screen has enough interactive complexity (click-to-cite transcript navigation, score bars, expandable panels) that raw JS would be painful. Vite makes the dev loop fast. There are no server-side rendering requirements here, so Next.js would've been unnecessary overhead.

**Trade-off:** The single-file approach keeps it simple but doesn't scale well if the app grows. If this became a real product, you'd split into proper component files, add a router, and use a state manager for cross-component data.

---

## 4. Backend & API Layer

**FastAPI.** Three interview endpoints + one voice proxy. The entire session state lives in a Python dict (`_sessions: dict[str, InterviewSession]`) in memory for the lifetime of the process. No database.

```python
# api.py
_sessions: dict[str, InterviewSession] = {}
```

### Endpoints

**`POST /session/start`**

Takes `StartRequest` (role, focus area, background, difficulty, topics, interviewer persona, interview mode). Validates that the interviewer seniority is strictly higher than the candidate's difficulty level — you can't have a junior interviewer grilling a senior candidate. Creates an `ImmutableContext` (a frozen Pydantic model with all session config), builds an `InterviewSession`, and runs the LangGraph pipeline until it hits the first `human_input` pause. Returns the first question.

**`POST /session/answer`**

Takes `session_id + answer`. Injects the answer into the paused LangGraph state, resumes the pipeline, and returns the next question (or signals completion if the interview is done).

**`GET /session/report`**

Retrieves the coach report from in-memory session state. Attaches the serialized turn log so the frontend can render the full transcript. Also stores the report in `_reports` dict with a `report_id` (UUID) for sharing and PDF download. Returns `report_id` in the response.

**`GET /report/{report_id}`**

Returns a stored report by its shareable ID. Works as long as the backend process is running (in-memory storage — not persisted across restarts). The frontend uses this for shared report links: `?report_id={id}` URL param loads the report directly without a session.

**`GET /session/report/pdf`**

Generates and returns a PDF of the interview report for a given `session_id`. If the report hasn't been fetched via `/session/report` yet, generates it on-demand. Returns `application/pdf` bytes with `Content-Disposition: attachment`.

**`GET /report/{report_id}/pdf`**

Same as above but by `report_id` — works even when the session is no longer tracked. Used by the frontend PDF download button in shared-link mode.

**`POST /voice/speak`**

Proxies to ElevenLabs. Takes the question text, calls ElevenLabs with the server-side API key, and returns the audio bytes directly. The API key never touches the frontend.

### Why no database?

For the current scope (single-process server, demo use), in-memory is fine. Sessions are cheap — each one is a few KB of Pydantic models. The trade-off is obvious: a server restart kills all active sessions. If this were a real product, you'd serialize `InterviewState` to a Redis cache or a document store like MongoDB (LangGraph also has a Postgres-backed checkpointer you could swap in).

---

## 5. Orchestration — How the Pipeline Works

This is the heart of the system. The pipeline is built with **LangGraph**, which is a graph-based workflow library built on top of LangChain. You define nodes (functions) and edges (transitions between them), compile it into a graph, and it handles execution, state passing, and checkpointing.

### The graph (from `orchestrator/graph.py`)

```
init
 ↓
interviewer  ←───────────────────────┐
 ↓                                    │
human_input (PAUSE — wait for user)  │
 ↓                                    │
evaluator                            │
 ↓                                    │
derive_signals                       │
 ↓                                    │
strategy                             │
 ↓                                    │
append_turn                          │
 ↓                                    │
[route_after_append]─────────────────┘
       ↓
      coach → END
```

The graph is compiled once and reused for every session. LangGraph's `MemorySaver` checkpointer maintains per-session state in memory, keyed by `thread_id` (the session ID). When a turn is submitted, LangGraph resumes exactly where it left off.

The `interrupt_before=["human_input"]` parameter is what makes the pause work. LangGraph stops the graph before the `human_input` node and waits for an external update. When `session.submit_answer(text)` is called, it does `g.update_state(cfg, {"human_input": answer})` and then resumes.

### Node responsibilities

| Node | File | What it does |
|---|---|---|
| `init` | `nodes.py` | Sets initial derived signals, sets first topic |
| `interviewer` | `nodes.py` | Calls `ask()` — generates a question |
| `human_input` | `graph.py` | Copies the user's answer into state |
| `evaluator` | `nodes.py` | Calls `evaluate()` — scores the answer |
| `derive_signals` | `nodes.py` | Recomputes coverage%, trajectory, difficulty |
| `strategy` | `nodes.py` | Calls `decide()` — picks next action |
| `append_turn` | `nodes.py` | Assembles and stores the `TurnRecord` |
| `coach` | `nodes.py` | Calls `generate_report()` — final report |

### The routing logic (from `orchestrator/edges.py`)

After `append_turn`, a conditional edge decides what comes next:

```python
def route_after_append(state):
    if state.is_complete:           return NODE_COACH
    if last_turn.topic == "closing": return NODE_COACH
    if last_action == WRAP_UP:       return NODE_INTERVIEWER  # ask closing question first
    if phase == CLOSING:             return NODE_COACH
    return NODE_INTERVIEWER
```

The subtle part: when Strategy decides `WRAP_UP`, the graph doesn't jump straight to Coach. It routes back to Interviewer first so the interviewer can say a proper goodbye and ask if the candidate has any final questions. Only *after* the candidate answers that closing question does the graph route to Coach.

### Guardrails (from `orchestrator/guardrails.py`)

The Strategy agent makes a decision, but guardrails can override it before it takes effect. They run deterministically after the LLM call:

1. **Turn limit**: If `turn_count >= target_turn_count`, force `WRAP_UP` regardless of what Strategy said.
2. **Weak candidate detection**: If ≥50% of substantive turns are weak (low scores + red flags), shorten the interview by 2 turns. Also blocks `PROBE` and `CHALLENGE` actions for struggling candidates.
3. **Depth ceiling**: If the evaluator flagged `depth_ceiling`, block `PROBE` and force a `PIVOT`.
4. **Consecutive cap**: If the same topic has been probed 3+ times in a row, force a `PIVOT`.
5. **Honest uncertainty**: If the candidate admitted they don't know something (`honest_uncertainty` flag), block `PROBE` and soften to a follow-up with `SIMPLER_REFRAME`.
6. **Intent integrity**: `PROBE` and `FOLLOW_UP` actions *must* have a non-`NONE` follow_up_intent. If Strategy outputs one without, it gets converted to a `PIVOT`.

The guardrails exist because pure LLM decisions are inconsistent under edge cases. They enforce structural correctness that you don't want to trust an LLM to get right every time.

---

## 6. The Four Agents (and what they really are)

### Interviewer Agent (`agents/interviewer/`)

**Purpose:** Generate the next question the candidate sees.

**Inputs:** Full `InterviewState` — session config, all past turns, the strategy mailbox (what to ask about and why), and evaluator signals from the last turn.

**Outputs:** A plain-text question string.

**How it works:**

There are three distinct cases:
- **Opening turn:** Single-shot LLM call with a prompt telling it to introduce itself and ask "tell me about yourself." No conversation history needed.
- **Closing turn:** Single-shot LLM call with recent conversation history, asking it to close warmly and ask if the candidate has questions.
- **All other turns (follow-ups):** Multi-turn chat call. This is where the real behavior lives.

For follow-up turns, it builds a list of `Content` objects that replicate the real conversation: the interviewer's prior questions as `model` turns, the candidate's answers as `user` turns. Then it appends the candidate's latest answer with a task directive attached — a hidden instruction block that tells the LLM exactly what to do: which answer-strength tier to use (strong/average/weak), what to acknowledge, what angle to probe, what intent to pursue, which questions were already asked (to avoid repeats).

The temperature is 0.7 — higher than evaluator and strategy (0.2) because you want conversational variety in how questions are phrased.

**Post-processing:** After getting a response, it strips markdown, removes leading labels ("Acknowledgment:", "Question:"), and trims everything after the last `?`. The interviewer must always end with exactly one question.

**Fallback:** If the LLM call fails after retries, it returns a hardcoded fallback question appropriate to the current phase (opening/questioning/closing).

**Is this a true agent?** No. It's an LLM call with a well-structured prompt. It doesn't choose *what* to ask about — that's the Strategy agent's job. It only determines *how* to phrase the question it's been told to ask.

---

### Evaluator Agent (`agents/evaluator/`)

**Purpose:** Score the candidate's answer on four dimensions and set diagnostic flags.

**Inputs:** The current question, the candidate's answer, recent turn history (last 3 turns for cross-turn context), prior scores on this topic, the difficulty level, and the interview mode.

**Outputs:** An `EvaluatorOutput` object:
- 4 integer scores (1–5): `technical_depth`, `communication_quality`, `epistemic_calibration`, `groundedness`
- 8 boolean flags: `vague_answer`, `bluffing_risk`, `unsupported_claim`, `shallow_terminology`, `honest_uncertainty`, `very_short_answer`, `off_topic`, `depth_ceiling`
- `follow_up_signals`: specific things from the answer worth probing (e.g., "Kafka consumer group", "migrated from monolith")
- `cross_turn`: whether the answer contradicts a previous answer, or recycles the same example
- `reasoning`: a short explanation of the scores

**Special case handling:** Before calling the LLM at all, it checks for two special inputs:
- **Feedback request** ("how did I do?", "can I get a report?"): Returns a neutral score with a `CANDIDATE_FEEDBACK_REQUEST` signal. Strategy sees this and immediately wraps up.
- **Candidate question** ("what's the culture like?"): Returns a neutral score with a `CANDIDATE_QUESTION` signal. The interviewer handles it by answering the question and continuing.

**Temperature:** 0.2 — deliberate. Evaluation should be deterministic and consistent, not creative.

**Is this a true agent?** No. It's a single LLM call with a structured JSON schema output. The "reasoning" it produces is for human readability, not for guiding its own next action. It doesn't decide what to do next.

---

### Strategy Agent (`agents/strategy/`)

**Purpose:** Decide what happens next in the interview — which topic, what action, at what difficulty, with what intent.

**Inputs:** Everything: turn count, topic coverage, depth ceilings, evaluator scores and flags, follow-up signals, consecutive action counts, score trajectory, the candidate's last answer, recent history, interview mode, and (when available) compressed web-retrieved company/industry context.

**Outputs:** A `StrategyDecision`:
- `next_action`: one of `probe`, `follow_up`, `pivot`, `challenge`, `recover`, `wrap_up`
- `target_topic`: which topic to address
- `follow_up_intent`: what kind of follow-up (validate_claim, clarify_vagueness, explore_story, test_boundary, simpler_reframe, none)
- `difficulty_adjustment`: increase / decrease / hold / none
- `reasoning`: why this decision was made

The Strategy agent sees a rich prompt: it knows how many turns have happened, which topics have been covered, which have hit a ceiling, what the coverage percentage is, what the trajectory looks like (improving/declining/stable), and what the evaluator said about the last answer. It uses all of this to make a judgment call.

After the LLM decision comes back, guardrails run and may override it.

**Temperature:** 0.2 — decisions need to be stable and consistent.

#### Web Retrieval Layer (`agents/strategy/retrieval.py`)

The Strategy Agent now has real web search tool integration — not just prompt references, but actual HTTP calls to search APIs, with LLM compression and session caching.

**Trigger logic (pure Python, no LLM):** `_assess_retrieval_need()` decides whether retrieval is worthwhile:
- **Always retrieves** if a specific company is identified in the role/focus/background context
- **Never retrieves** for generic focus areas: behavioral, leadership, estimation, general
- **Retrieves for industry-specific** contexts: fintech, healthtech, marketplace, SaaS, ML product, etc.
- **Retrieves if candidate background** mentions specific employers ("at Stripe", "formerly at Google")
- Only triggers during **turns 0–2** (early in the session, when context is most useful)
- Once retrieved, the result is **cached in `InterviewState.retrieved_context`** for the rest of the session. Subsequent calls to `run_retrieval_if_needed()` return `None` immediately (cache hit).

**Company extraction (`_extract_company()`):** Checks a curated list of well-known tech/product companies first (highest precision), then falls back to regex patterns for "at CompanyName" / "for CompanyName" patterns from the combined role + focus + background text.

**Search provider hierarchy (multi-provider fallback):**
1. **Tavily** (`TAVILY_API_KEY`) — preferred; AI-curated snippets with clean content extraction
2. **Serper.dev** (`SERPER_API_KEY`) — Google Search API; used if Tavily is unavailable
3. **DuckDuckGo instant answer API** — free, no key required; used as last resort (limited results)

Each provider is called with a 6-second timeout. Domain blocklist (`quora.com`, `reddit.com`, etc.) filters low-quality SEO content from any provider.

**Query construction:** At most 2 queries per session. For company contexts: `"{Company} product strategy {year}"` + `"{Company} product roadmap launches {year}"`. For industry contexts: `"{focus_area} industry trends {year}"`.

**LLM compression (`_compress()`):** Raw snippets (up to 5) are compressed into an 80–120 word factual summary via a single Gemini Flash Lite call (temperature 0.1, system prompt instructs: no PR language, no speculation, focus on products/strategy/metrics). Falls back to a truncated first snippet if the LLM call fails.

**Prompt injection (`_format_retrieval_block()`):** The compressed context is injected as a labelled block **before** the interview context section in `build_strategy_user_prompt()`. The block includes an explicit instruction: *"Use this context to make questions more specific and realistic. Do NOT quiz the candidate on recent news — use context for depth."* If retrieval was not performed or failed, the block is empty string (zero prompt impact).

**Graceful failure:** Any exception at any stage — network error, search provider down, LLM compression failure — is caught and logged. The interview continues normally. `retrieved_context` stays `None` and the prompt is unaffected.

**State integration:** `strategy_node` in `nodes.py` calls `run_retrieval_if_needed(state)` before the LLM decision. If new retrieval occurs, `retrieved_context` is added to the returned state dict. The `effective_retrieval` pattern:
```python
new_retrieval = run_retrieval_if_needed(state)          # None if cache hit or not needed
effective_retrieval = new_retrieval or state.retrieved_context  # reuses cache across turns
decision, guardrail = decide(state, plan=plan, retrieved_context=effective_retrieval)
```

**What retrieval improves:** The Strategy agent uses the compressed context to make its `reasoning` field more specific — instead of generic probes ("ask about their metrics approach"), it can ground questions in the company's actual product landscape ("Stripe recently expanded to business banking — probe whether candidate considered payment infrastructure vs. banking infrastructure tradeoffs"). This improves the *realism* and *contextual depth* of follow-up questions, not just their generic quality.

**Is this a true agent?** This is the closest thing to a real agent in the system. It has genuine situational awareness (full session context), makes decisions that affect the overall arc of the interview, and now has a real tool (web search) it can invoke. The tool use is bounded and controlled — it fires at most once per session, is triggered by a deterministic heuristic, and the output is compressed before being injected. It's a decision-making LLM call with rich context and a scoped retrieval tool — not a fully autonomous planning agent, but a meaningfully more capable component than a simple prompted LLM.

---

### Coach / Report Agent (`agents/coach/`)

**Purpose:** Generate the final performance report.

**Inputs:** All `TurnRecord`s (excluding the closing turn), the session context (role, focus area, difficulty), pre-computed aggregate scores, the derived score trajectory, and the weakness severity.

**How it works — up to 3 LLM calls, with a mandatory pure-Python evidence layer:**

**Step 0 — Evidence retrieval (no LLM, always runs):**
`agents/coach/evidence.py` curates the transcript before any LLM sees it. It computes:
- **Strongest / weakest turns** by weighted combined score (domain dimensions weighted 0.35 each, communication 0.15)
- **Vague/shallow pattern turns** (vague_answer or shallow_terminology flags, or groundedness ≤ 2)
- **Recovery moments** (weak turn immediately followed by a materially stronger one)
- **Cross-turn inconsistencies** (same topic, depth score swing ≥ 2 points)
- **Trajectory notes** (first-half vs. second-half average with peak/low turn identified)

This curated bundle is formatted and prepended to the analysis prompt, so the LLM receives targeted signals rather than just a raw transcript dump. It produces more specific observations.

**Call 1 — Analysis:** Gets the curated evidence context + full transcript. Identifies patterns: strongest/weakest turns, trajectory, contradictions, per-topic performance. Returns JSON.

**Call 2 — Report draft:** Takes the analysis JSON + full transcript reference + role context + weakness severity framing. Generates the full `CoachReport` JSON.

**Step 3 — Quality validation (no LLM):**
`validate_report_quality()` in `evidence.py` checks the draft for:
- Banned phrases in suggestions ("structure your answers", "use the STAR method", etc.)
- Weak or placeholder evidence excerpts
- Too-short observations (likely generic)
- Duplicate practice recommendations

**Call 3 — Critique/repair (conditional — only fires if quality check fails):**
If `validate_report_quality()` finds issues, one targeted repair call is made using `COACH_CRITIQUE_SYSTEM_PROMPT`. It receives the specific issues list + the draft + transcript reference and returns a corrected JSON. If the repair doesn't reduce issues, the original draft is kept. This pass is fully bounded — at most 1 call, 0 if quality is already good.

**Deterministic overrides (always applied after all LLM calls):**
- `overall_score`: always computed from the actual weighted average of evaluator scores. Never LLM-generated.
- `score_summary.scores`: always from actual evaluator data.
- `strongest_dimension` / `weakest_dimension`: computed by `_extremes()` with a domain-first tiebreaker.
- `topic_coverage`: computed from actual topic tracking.
- `weakness_severity`: computed from actual score gap ("none" / "minor" / "significant").

These are injected by `_inject_deterministic()` regardless of what the LLM said.

**Report storage and sharing:**
When `/session/report` is called, the report dict (including transcript `_turns`) is stored in `_reports` in-memory dict with a `report_id` (UUID). The response includes the `report_id`. This enables:
- **Shareable links:** `GET /report/{report_id}` returns the stored report. The frontend constructs `?report_id={id}` share URLs. If `?report_id` is present on load, the app goes directly to the report screen.
- **PDF download:** `GET /session/report/pdf` and `GET /report/{report_id}/pdf` generate a professional A4 PDF via `agents/coach/pdf_generator.py` (uses `fpdf2`, no system dependencies).

**PDF generation (`agents/coach/pdf_generator.py`):**
Uses `fpdf2` (pure Python). Sections: header block, overall score hero, score bars, strongest/weakest cards, strengths, growth areas, detailed feedback, practice recommendations, topic coverage table, full transcript. All text sanitized through `_safe()` to handle unicode characters that latin-1 can't encode.

**Fallback:** If any LLM call fails or produces unparseable JSON, `_fallback_report()` generates a structurally valid report from raw evaluator data.

**Is this a true agent?** Closer than before. The evidence retrieval layer genuinely pre-analyzes the transcript and informs what the LLM reasons about — it's not just prompt engineering around a dump. The conditional critique pass means the system can self-correct. But there's no tool use, no planning, no persistent memory. It's a multi-step reasoning pipeline with deterministic bookends.

---

## 7. Prompt Engineering

### The system prompt / user prompt split

Every agent uses the same pattern: a **system prompt** (static, injected once as the `system_instruction`) and a **user prompt** (dynamic, built fresh each turn).

- System prompts define the persona, rules, output format, and behavior constraints.
- User prompts inject the current context: transcript, scores, flags, session config, role context.

This split matters for caching and cost, but here it's mainly architectural clarity.

### Dynamic prompt construction

**Role-aware context:** Every evaluator, coach analysis, and coach report prompt includes a `_role_scoring_context(role, focus_area, difficulty_target)` block that re-interprets the four scoring dimensions for the specific role. For a Product Manager: `technical_depth` = "product thinking depth", `groundedness` = "metrics depth and named examples". For an SWE: `technical_depth` = "architectural understanding and operational tradeoffs". This is injected into every LLM call in the evaluation/reporting path so the model never confuses a PM answer with a backend engineering answer.

**Seniority calibration:** `_seniority_context(difficulty_target)` generates a paragraph that tells both the evaluator and the coach what "good" means at this level. An intern demonstrating clear structure scores strong. A director giving the same answer doesn't. This prevents the model from applying a uniform bar.

**The task directive (Interviewer):** The most complex dynamic prompt in the system. Built by `build_chat_task_directive()`, it's appended to the candidate's last answer in the chat history — the model doesn't see it as a separate instruction, it sees it as part of what the candidate said, after a `---` separator. It contains:
- Which acknowledgment level to use (strong/average/weak/blunder in grill mode)
- If `strong`: which specific signal from the answer to reference
- The topic, action, difficulty level
- What angle to pursue
- The last 6 questions asked (to avoid repeats)
- If it's a pivot: the transition note

**Weakness severity framing:** The coach report prompt includes a `⚡ MANDATORY` banner at the very top that tells the model how to frame the weakness section. Three tiers:
- `none`: "There is NO significant weakness. Do NOT manufacture a gap."
- `minor`: "Use ONLY softened language: 'slight improvement opportunity'."
- `significant`: "Call it out directly with specific transcript evidence."

This was added because the model would invent dramatic weaknesses even when all scores were clustered within 0.2 of each other.

### Context injection across turns

The evaluator gets a 3-turn history window for cross-turn analysis. The interviewer gets a 6-turn dialogue window for the chat history. The strategy agent gets the full topic coverage map and all evaluator scores from all turns. The coach gets the complete serialized transcript.

State flows through `AgentMailboxes`: the evaluator writes its output to `evaluator_to_strategy`; strategy writes its decision to `strategy_to_interviewer`. These are read and then cleared by the next node.

---

## 8. Scoring & Evaluation System

### The four dimensions

| Dimension | What it actually measures |
|---|---|
| `technical_depth` | Domain knowledge quality — role-interpreted (product thinking for PMs, code/architecture for SWEs) |
| `communication_quality` | HOW ideas are expressed — structure, clarity. NOT content quality. |
| `epistemic_calibration` | Accuracy of self-knowledge — does the candidate know what they know? |
| `groundedness` | Are claims anchored in specifics? Named tech, real metrics, named examples. |

Each is scored 1–5 per turn by the evaluator.

### Warm-up weighting

The first turn is always "tell me about yourself." It's treated differently: its scores are given a weight of 0.3 instead of 1.0 when computing aggregates. This prevents a nervously rambling introduction from dragging down the whole score.

### Aggregate score computation

```python
# orchestrator/signals.py — _aggregate_scores()
for turn in turns:
    weight = 0.3 if turn_index == 0 else 1.0
    weighted_sum += score * weight
aggregate = weighted_sum / total_weight
```

### Overall score (X/10)

Computed deterministically in `coach/agent.py._compute_overall_score()`:

```
avg_of_4_dimensions (on 1–5 scale)
→ normalize: ((avg - 1) / 4) * 10  → gives 0–10
→ bump: +0.3 if trajectory is IMPROVING, -0.3 if DECLINING
→ clamp to [1.0, 10.0]
→ round to 1 decimal
```

The trajectory bump rewards a candidate who starts rough but gets progressively better.

### Strongest / weakest dimension selection

`_extremes()` in `coach/agent.py`:
1. If the gap between max and min score is ≤ 0.3 → return ("", "") — balanced profile, no manufactured drama.
2. Otherwise: find max and min dimension.
3. **Domain-first tiebreaker:** If `communication_quality` is the top dimension but any domain dimension (`technical_depth`, `groundedness`, `epistemic_calibration`) is within 0.3 of it → prefer the domain dimension. Communication shouldn't overshadow genuine domain expertise.

### Score trajectory

`_trajectory()` in `orchestrator/signals.py`:
- Skip turn 0 (warm-up).
- Compare average `technical_depth` of the last 2 substantive turns vs. the 2 before that.
- Δ ≥ 0.5 → `IMPROVING`. Δ ≤ -0.5 → `DECLINING`. Otherwise → `STABLE`.
- Fewer than 3 substantive turns → `INSUFFICIENT_DATA`.

### Preventing hallucinated feedback

Two layers:

1. **Every piece of feedback must cite a turn index.** The coach prompts explicitly say: "Never fabricate content. Every evidence excerpt must paraphrase what the candidate actually said in that turn." The model is given a `TURN REFERENCE` block with every question and answer indexed by turn number.

2. **Deterministic injection.** The parts most vulnerable to hallucination (scores, strongest/weakest dimension, overall score, topic coverage) are computed from real data in Python and written into the report dict *after* the LLM call, overwriting whatever the model said.

### Role-specific dimension labels

The frontend displays role-appropriate labels instead of generic ones. The mapping is in `_role_dimension_labels()` in `coach/agent.py`:

| Role | `technical_depth` label | `groundedness` label |
|---|---|---|
| Product Manager | Product Thinking | Metrics Depth |
| Strategy/Consulting | Analytical Thinking | Quantitative Rigor |
| Data Scientist | ML / Data Depth | Specificity |
| SWE (default) | Technical Depth | Groundedness |

---

## 9. Grill Mode

Grill Mode is a tougher variant of the interview. It changes behavior across all four agents.

### What changes

**Interviewer:**
- System prompt gets `_GRILL_SYSTEM_ADDON` appended — instructs the interviewer to push for evidence on every answer, challenge assumptions, and reduce social warmth.
- Opening prompt signals a serious tone: "We'll be going into considerable depth today."
- Uses a different acknowledgment map (`_ACK_INSTRUCTION_GRILL`) with 4 tiers:
  - `strong`: Don't invent weaknesses. Deepen naturally — "How would you validate that? What tradeoffs would you consider?"
  - `average`: Neutral + "Walk me through your reasoning."
  - `weak`: "I'm not fully convinced." / "That assumption seems weak to me."
  - `blunder`: "That approach seems difficult to justify." / "Let's revisit that."

The `blunder` tier is grill-mode only. It fires when the evaluator detects bluffing risk + low scores, or off-topic + very short answer, or TD=1 + GR=1 simultaneously.

**Strategy:**
- More aggressive probing on strong answers (go 2–3 turns deep before pivoting).
- Less aggressive breadth warnings (you need fewer topics covered before being told to move on).
- Wraps up faster on 3+ consecutive weak turns.

**Evaluator:**
- Gets a stricter calibration note in the prompt: grill-mode applies higher bar for each seniority level.
- A "good" answer in grill mode needs more depth to score 4.

**Session config:**
- Minimum 10 turns enforced by the API (vs. 6 default for normal mode).
- Max 14 turns (vs. 12 in previous version).

**Frontend:**
- A pulsing red "GRILL MODE" badge appears in the interview header.
- The Start button turns red.
- Target turns is set to 10 automatically.

---

## 10. State Management

### The state model

All session state lives in `InterviewState` (`state/models.py`):

```python
class InterviewState(BaseModel):
    context: ImmutableContext     # frozen config — never changes
    turns: list[TurnRecord]       # append-only history of all turns
    derived: DerivedSignals       # recomputed after every turn
    mailboxes: AgentMailboxes     # inter-agent communication
    current_phase: InterviewPhase
    current_topic: str
    current_question: str
    current_answer: str
    is_complete: bool
    interview_plan: Optional[InterviewPlan]       # agentic planning layer
    conversational_state: Optional[ConversationalState]
    retrieved_context: Optional[RetrievalRecord]  # web retrieval cache (set at most once)
```

**`ImmutableContext`** is frozen (`frozen=True` Pydantic model). It contains everything set at session start — role, focus area, candidate background, difficulty, topics, persona card, interview mode. It never changes. This is intentional: the interview shouldn't shift its goals mid-session.

**`TurnRecord`** is the complete record of one exchange. It stores the question, answer, evaluator scores, flags, strategy decision, prompt versions used, and timestamp. It's append-only — you never mutate or delete a turn.

**`DerivedSignals`** is recomputed from scratch after every turn. It's calculated, not stored persistently — topic coverage percentages, current difficulty, consecutive action counts, score trajectory. This makes it easy to reason about: it's always a pure function of the turn history.

**`AgentMailboxes`** is how agents communicate. After the evaluator runs, it writes to `evaluator_to_strategy`. After strategy runs, it writes to `strategy_to_interviewer`. Each node clears the mailbox it consumed. It's a simple message-passing pattern.

### How LangGraph stores this

LangGraph wraps `InterviewState` inside a `GraphState` TypedDict:

```python
class GraphState(TypedDict):
    interview_state: dict   # serialized InterviewState
    human_input: Optional[str]
```

The `interview_state` is always a plain dict (JSON-serializable). Every node receives the current `GraphState`, deserializes it into `InterviewState`, runs its logic, and returns a partial update dict. The `_wrap()` function in `graph.py` handles this automatically for every node.

The `MemorySaver` checkpointer keeps one checkpoint per `thread_id` (session ID) in memory. When `submit_answer` is called, LangGraph looks up the checkpoint, resumes from the `human_input` node, runs forward, saves a new checkpoint, and pauses again.

---

## 11. Voice Layer

Two separate systems that work independently:

**Speech-to-text (browser-native, free):** `useSpeechToText()` hook uses `window.SpeechRecognition`. Streams words into the textarea in real time. Final results accumulate; interim results show `[listening...]`. No API call. Works only in Chromium browsers.

**Text-to-speech (server-proxied, ElevenLabs):** `useElevenLabs()` hook calls `POST /voice/speak`. The backend (`api.py`) proxies to ElevenLabs with:
- Model: `eleven_turbo_v2` (lowest latency)
- Voice: Rachel (`EXAVITQu4vr4xnSDxMaL`)
- Stability: 0.5, similarity_boost: 0.75

Backend returns raw `audio/mpeg` bytes. Frontend plays via `new Audio(URL.createObjectURL(blob))`. The voice degrades silently on 503 (key not configured) — `voiceAvailableRef.current = false`, and no more calls are attempted. This makes voice opt-in per deployment without code changes.

---

## 12. Tech Stack

### Frontend
- **React 18** (Vite)
- **Web Speech API** — speech-to-text (browser-native)
- **Fetch API** — all HTTP calls
- **Google Fonts**: Syne, Instrument Serif, DM Mono
- **Deployed:** Netlify (connected to GitHub, auto-deploys on push to main)

### Backend
- **Python 3.11+**
- **FastAPI** — API framework
- **Uvicorn** — ASGI server
- **Pydantic v2** — data models and validation
- **LangGraph** — graph-based workflow orchestration
- **httpx** — async HTTP for ElevenLabs proxy
- **python-dotenv** — env variable loading
- **Deployed:** Render.com (web service, free tier)

### AI / LLM
- **Google Gemini Flash Lite** (`gemini-flash-lite-latest`) — used for all 4 agents + retrieval compression
- **Google Gen AI Python SDK** (`google-genai`)
- API key: `GEMINI_API_KEY` (server-side only)

### Web Search (Strategy Agent retrieval — all optional)
- **Tavily** (`TAVILY_API_KEY`) — preferred search provider; AI-curated results
- **Serper.dev** (`SERPER_API_KEY`) — Google Search API fallback
- **DuckDuckGo instant answer API** — free fallback, no key required
- Provider hierarchy: Tavily → Serper → DuckDuckGo. All three are optional; if none are available, retrieval is simply skipped.

### Voice
- **ElevenLabs API** — text-to-speech
- API key: `ELEVENLABS_API_KEY` (server-side only, never exposed to client)

### Storage / Persistence
- **None.** Sessions live in-memory in the FastAPI process. No Redis, no DB.

### Dev tools
- Git + GitHub
- `.env` file (never committed — contains both API keys)

---

## 13. Design Decisions & Trade-offs

### Why LangGraph instead of a simpler loop?

The interview has non-linear control flow. After each answer, the next step depends on: what the evaluator found, what guardrails say, whether the interview should end. A plain `while True` loop with `if/elif` chains would work for the happy path but gets messy fast when you add guardrails, fallbacks, phase transitions, and the closing sequence. LangGraph gives you explicit nodes, explicit edges, and a checkpointer for free. The main cost is the learning curve and a bit of abstraction overhead — every node needs to serialize and deserialize state.

### Why one model (Gemini Flash Lite) for all 4 agents?

Cost and simplicity. Flash Lite is fast and cheap. The prompt engineering does the differentiation work — each agent has very different system prompts, temperatures, output formats, and instruction sets. A stronger model (Gemini Pro, GPT-4) would improve report quality but would cost more per session. The current model handles the structured JSON output tasks (evaluator, strategy, coach) well at temperature 0.2. The interviewer benefits from the slightly creative temperature (0.7) to vary phrasing.

### Why in-memory session storage?

For a prototype or demo, in-memory is genuinely fine. It avoids a database dependency, keeps the setup simple, and sessions are short-lived. The clear trade-off: a server restart drops all active sessions, and you can't scale horizontally without session affinity. For a production system, you'd add a Redis-backed LangGraph checkpointer and store session metadata in a DB.

### Why not stream the LLM responses?

The current implementation waits for the full response before returning it to the frontend. This means the user sees a "thinking" indicator for 2–5 seconds between their answer and the next question. Streaming would feel faster, but adds complexity: you'd need WebSockets or Server-Sent Events, and you'd need to handle partial JSON in the evaluator/strategy calls. The evaluator and strategy outputs must be complete JSON before they can be used, so streaming only helps for the interviewer. The trade-off was made in favor of simplicity for now.

### Why split evaluator and strategy into separate agents?

**Separation of concerns.** The evaluator's job is purely analytical — it scores what just happened. The strategy's job is forward-looking — it decides what comes next. Mixing them would create a confused prompt: "evaluate this answer AND decide what to do next AND know about topic coverage AND know about difficulty progression." Keeping them separate makes each prompt tighter and easier to reason about and test. The evaluator never needs to know about topic coverage. The strategy never needs to think about how to phrase an acknowledgment.

### Why up to 3 LLM calls for the coach report (and a pure-Python evidence layer)?

One LLM call caused the model to skip nuanced analysis and produce generic observations. Splitting into analysis → report forces a reasoning step before generation.

The evidence layer (`evidence.py`) runs before any LLM call and pre-computes: strongest/weakest turns by weighted score, vague-pattern turns, recovery moments, cross-turn inconsistencies, and a trajectory narrative. The LLM then receives curated signals rather than a raw transcript dump — it can reference "Turn 3 was your weakest, here's why" instead of discovering it while also trying to write feedback.

The optional third call (critique/repair) only fires when the pure-Python quality validator finds banned phrases, placeholder evidence, or too-short observations. It's bounded at one attempt and uses the validated issues list as an explicit fix target rather than just re-running the report prompt. In practice it fires rarely — when the LLM's first draft is already clean, it adds zero latency.

The deterministic bookends (scores, extremes, coverage, severity) are always overwritten after all LLM calls. The LLM can't pick its own score.

### API key security

Both API keys live in server-side environment variables. The frontend never sees them. The ElevenLabs key is proxied through a backend endpoint. The Gemini key is used only in Python. This is non-negotiable: embedding API keys in frontend JS is a security violation, and any user could extract and abuse them.

---

## 14. True Agent vs. Prompted LLM — Honest Answer

"Agent" is an overloaded word. Here's what each component actually is:

### What makes something a "true agent"?

A true autonomous agent can:
1. Perceive its environment
2. Make decisions
3. Take actions that affect the environment
4. Do this in a loop, including planning multi-step sequences

### Component-by-component breakdown

| Component | What it really is |
|---|---|
| **Interviewer** | Prompted LLM. Given a system prompt, a chat history, and a task directive. Generates text. No decisions. |
| **Evaluator** | Prompted LLM. Reads Q+A, returns structured JSON. One call per turn. No decisions, no actions. |
| **Strategy** | Closest to an agent. Has meaningful situational awareness, makes decisions that affect interview flow. Now also has a real web search tool (`retrieval.py`) — fires at most once per session via a deterministic heuristic, compresses results via LLM, injects as context. Doesn't plan multi-step or loop autonomously, but has genuine tool use with caching. |
| **Coach/Report** | Multi-step pipeline: pure-Python evidence retrieval → analysis LLM call → report LLM call → pure-Python quality validation → conditional repair LLM call (only if quality check fails) → deterministic injection. Evidence layer genuinely pre-analyzes the transcript and shapes what the LLM reasons about. Self-correcting via bounded critique loop. Deterministic bookends ensure scores/extremes/coverage are never hallucinated. |
| **Guardrails** | Not an LLM at all. Pure deterministic Python logic. |
| **LangGraph pipeline** | Not an AI. It's a state machine / workflow runner. The "orchestration" is explicit code, not an AI making meta-decisions. |
| **`InterviewSession`** | Not an AI. It's a Python class that drives the LangGraph graph. |

### The honest summary

This system is a **prompt-engineered multi-LLM pipeline** with a workflow orchestrator. It's not a system of autonomous agents that make their own decisions about what to do. The orchestration logic is explicit Python code. The "agents" are well-prompted LLM calls with clearly defined inputs and outputs.

That said, the **Strategy component** has genuine decision-making behavior — it reads rich situational context and makes non-trivial choices. And the **Guardrails** add deterministic safety on top of those choices. This combination produces behavior that *feels* adaptive and intelligent, even though the underlying mechanism is: structured prompt → structured JSON → code-level decision execution.

The reason this matters for interviews: if someone asks "why is this an agent and not just a chatbot?", the real answer is: (1) there are multiple specialized LLM calls doing different jobs, (2) the output of one call feeds into the next as structured data, (3) the pipeline loops and branches based on computed signals, and (4) the final behavior emerges from the interaction of these components — no single LLM call is doing everything. That's a legitimate and useful architecture even if it doesn't match the "fully autonomous AI agent" hype.

---

## 15. Possible Interview Questions + Strong Answers

---

### Architecture Questions

**Q: Why did you use a multi-agent architecture instead of just one LLM doing everything?**

A: Four reasons. First, separation of concerns — evaluation and question generation are genuinely different tasks with different optimal temperature settings, different output formats, and different failure modes. Mixing them degrades both. Second, each agent can be improved independently — I can tighten the evaluator rubric without touching the interviewer prompt. Third, the structured JSON output from the evaluator becomes a reliable data contract that the strategy agent reasons over — it's not just passing text around. Fourth, adding guardrails is only possible because the strategy outputs a structured decision object that code can inspect and override.

**Q: How does state actually flow between the agents?**

A: Through a central `InterviewState` Pydantic model that lives in LangGraph's checkpointer. Each node receives the full state, does its work, and returns a partial update dict. The `AgentMailboxes` pattern handles direct agent-to-agent communication: the evaluator writes to `evaluator_to_strategy`, strategy writes to `strategy_to_interviewer`, each node clears the mailbox it consumed. The state itself is serialized to a plain dict between nodes, which is what LangGraph's MemorySaver persists.

**Q: Why LangGraph specifically?**

A: For the pause-and-resume pattern. The interview is fundamentally async — the pipeline needs to stop after generating a question, wait for a human answer (which comes from an HTTP POST potentially seconds or minutes later), and resume from exactly the same point. LangGraph's `interrupt_before` mechanism handles this elegantly. You could replicate it with Redis and a custom state machine, but you'd be rebuilding what LangGraph already provides. The trade-off is the learning curve and some serialization overhead.

---

### Agent Design Questions

**Q: The strategy agent is the most interesting one — what does it actually decide?**

A: It picks the next action from six options: `probe` (drill deeper on same topic), `follow_up` (stay on topic but soften), `pivot` (move to a new topic), `challenge` (push back on a claim), `recover` (course-correct if candidate is lost), or `wrap_up` (end the interview). It also picks the target topic, the follow-up intent (what angle to pursue), and whether to increase/decrease/hold difficulty. It receives full session context: coverage percentages, depth ceilings, consecutive action counts, evaluator scores, follow-up signals extracted from the answer, and the score trajectory. It's the component that gives the interview its "adaptive" feel.

**Q: How do you prevent the evaluator from hallucinating scores?**

A: Two ways. The evaluator prompt has very explicit rubrics with precise criteria for each score level (not "good/bad" — specific conditions). It runs at temperature 0.2 for consistency. But more importantly, the scores from the evaluator are used as structured data by all downstream components — there's no way to "hallucinate" a 4 and have it pass unnoticed. The coach report's final scores are deterministically computed from the actual evaluator outputs in Python. The LLM never picks the overall score.

**Q: What happens if one of the LLM calls fails?**

A: Every agent has a fallback path. The evaluator falls back to neutral mid-range scores with no flags. Strategy falls back to a follow-up on the current topic. The interviewer has hardcoded fallback questions per phase. The coach has `_fallback_report()` which generates a structurally valid report from raw evaluator data. Retries with exponential backoff (`call_with_retry` in `agents/llm_utils.py`) happen before the fallback. The interview never hard-crashes — it degrades gracefully.

---

### Scalability Questions

**Q: Your sessions are in memory. How would you scale this?**

A: Two things need to change. First, swap LangGraph's `MemorySaver` for a persistent checkpointer — LangGraph has a built-in Postgres checkpointer. This makes sessions durable and allows horizontal scaling. Second, add session stickiness if you're running multiple instances without a shared checkpointer, or just use the Postgres option and let any instance handle any request. The actual interview logic doesn't need changes — it's all stateless computation on the interview state.

**Q: What's the latency profile per turn?**

A: Each turn makes 3 sequential LLM calls: evaluator → strategy → interviewer (coach only at the end). At temperature 0.2 and with Gemini Flash Lite, each call takes roughly 1–3 seconds. So end-to-end per turn is 3–9 seconds. The main optimization levers are: (1) switch to a faster model, (2) parallelize evaluator and strategy if they can be decoupled (they can't fully — strategy needs evaluator output), (3) stream the interviewer response to show text progressively. Currently none of these are implemented — the trade-off was simplicity over latency.

The web retrieval (when triggered) adds latency only on the first eligible turn — typically turn 0 or 1 when the system just started the first answer evaluation. The search call has a 6-second timeout, and the compression LLM call adds another 1–2 seconds. After that first trigger, the result is cached and retrieval adds zero latency to all subsequent turns. On turns where retrieval is not needed (generic focus areas, cache already populated), the overhead is a Python function call that returns immediately.

**Q: How would you handle multiple concurrent users?**

A: The current FastAPI setup is async (using async endpoints for the voice proxy, sync for the LangGraph calls). Adding more concurrent users hits two constraints: API rate limits on Gemini, and the in-memory session dict becoming a bottleneck. For Gemini: use the batch API or implement per-user rate limiting. For sessions: the persistent checkpointer approach above handles it. FastAPI with Uvicorn already handles concurrent HTTP requests fine — the bottleneck is the LLM calls themselves.

---

### Prompt Engineering Questions

**Q: How do you prevent the interviewer from repeating questions?**

A: Every task directive injected into the chat history includes the last 6 questions with their topic labels: `[prioritization] "Walk me through how you decided to cut feature X."` The prompt explicitly says: "Do NOT repeat (conceptually or semantically)." The model sees the pattern and avoids it. Additionally, the strategy agent picks `follow_up_intent` to steer the angle, which naturally produces different questions even on the same topic.

**Q: How does the role-aware prompting work?**

A: There's a function `_role_scoring_context(role, focus_area, difficulty_target)` that generates a context block injected into both the evaluator and coach prompts. It re-maps the four scoring dimensions to role-appropriate meanings. For a PM, `technical_depth` becomes "product thinking quality." For a strategy consultant, `groundedness` becomes "quantitative rigor — named companies, real estimates, numbers." This block is generated dynamically at call time, not hardcoded per role. The function pattern-matches the role string against keyword lists to pick the right block.

**Q: How do you calibrate for seniority?**

A: The `_seniority_context(difficulty_target)` function returns a paragraph that's injected into both evaluator and coach prompts. At junior level: "Strong performance = clear structured reasoning, concrete examples from coursework. Do NOT require enterprise-scale depth." At staff level: "Apply a high bar. Generic mid-level answers score 2–3." This changes what the model considers "strong" vs "weak" without requiring different rubrics. The difficulty level also affects which guardrail thresholds kick in.

---

### AI System Design Questions

**Q: What's the difference between how you use the evaluator and how RAG systems use retrieval?**

A: RAG retrieves external knowledge to augment a prompt. The evaluator is the opposite — it extracts structured knowledge from the candidate's answer to inform the system's next action. The "retrieval" is from what was just said, not from a knowledge base. The evaluator's output (scores, flags, follow_up_signals) is the structured signal that makes the system adaptive. Without it, you'd have no basis for deciding whether to probe or pivot.

**Q: How do you know the report is actually grounded in the transcript and not hallucinated?**

A: Three-layer approach. First, the coach receives a `TURN REFERENCE` block with every question and answer indexed by turn number — it can only cite real turns. Second, the prompt explicitly says "Never fabricate content. Every evidence excerpt must paraphrase what the candidate actually said." Third, the deterministic injection in `_inject_deterministic()` overwrites scores, strongest/weakest dimension, overall score, and topic coverage with Python-computed values from real evaluator data. The LLM's contribution is the natural-language narrative — the factual data layer is computed, not generated.

**Q: Why not fine-tune a model on mock interview data instead of prompt engineering?**

A: Two practical reasons. First, I don't have labeled interview data — fine-tuning requires examples of "good" vs "bad" question generation at the right moment, which is expensive to produce. Second, the behavior is highly configurable (role, difficulty, persona, grill mode) — fine-tuning would produce a model optimized for one configuration. Prompt engineering lets you change behavior at runtime by changing the prompt. The trade-off is latency (larger prompts = more tokens = slower) and cost vs. a fine-tuned model that could be smaller and faster for a specific task.

---

*This document reflects the actual implementation as of May 2026. All code references are to the real files in the project.*
