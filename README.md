# AI Interview Coach

An adaptive mock interview platform powered by a multi-agent AI pipeline. The system conducts realistic interviews, evaluates answers in real time, adapts follow-up questions based on performance, and generates a detailed coaching report at the end.

---

## Features

- **Adaptive questioning** — four LLM agents (Interviewer, Evaluator, Strategy, Coach) orchestrated via LangGraph
- **Multi-turn chat** — the interviewer genuinely acknowledges candidate answers before asking the next question
- **Dynamic focus areas** — configurable topics, difficulty, and interviewer persona
- **Voice I/O** — speech-to-text via Web Speech API; text-to-speech via ElevenLabs (optional)
- **Detailed report** — scores across technical depth, communication, epistemic calibration, and groundedness; topic coverage; strengths and improvement areas
- **PM-first defaults** — ships with Product Manager defaults; fully configurable for any role

---

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python · FastAPI · LangGraph · Google Gemini API |
| Frontend | React (Vite) · single-file component |
| LLM | `gemini-flash-lite-latest` (all four agents) |
| Voice (optional) | ElevenLabs TTS (server-proxied) · Web Speech API |

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/DevendraJeswani/AI-Interviewer.git
cd AI-Interviewer
```

### 2. Backend

```bash
cd backend
python -m venv venv
# Windows:  venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt

# Create your .env from the example
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

Run the backend:

```bash
python -m uvicorn api:app --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Configuration

### Required

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key — get one at [aistudio.google.com](https://aistudio.google.com/app/apikey) |

### Optional

| Variable | Description |
|---|---|
| `ELEVENLABS_API_KEY` | ElevenLabs API key for voice readback. Leave empty for text-only mode. |

All variables go in `backend/.env` (never committed).

---

## Project Structure

```
AI-Interviewer/
├── backend/
│   ├── agents/
│   │   ├── coach/          # Report generation agent
│   │   ├── evaluator/      # Answer scoring agent
│   │   ├── interviewer/    # Question generation agent (multi-turn chat)
│   │   ├── strategy/       # Next-action decision agent
│   │   └── llm_utils.py    # Shared retry logic
│   ├── config/             # Agent configuration
│   ├── orchestrator/       # LangGraph graph, nodes, guardrails, session
│   ├── prompts/            # Prompt registry
│   ├── report/             # Report data models
│   ├── state/              # Interview state, enums, models
│   ├── validation/         # LLM output validation
│   ├── api.py              # FastAPI application
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── App.jsx         # Full UI (setup, interview, report screens)
    │   ├── main.jsx
    │   └── api/client.js   # Backend API client
    ├── package.json
    └── vite.config.js
```

---

## Agent Architecture

```
human_input
    │
    ▼
[Evaluator]  — scores the answer, extracts signals
    │
    ▼
[Strategy]   — decides next action (probe / pivot / follow-up / wrap-up)
    │
    ▼
[Interviewer]— generates next question using multi-turn chat format
    │
    ▼
(repeat until target turns reached)
    │
    ▼
[Coach]      — generates full feedback report
```

---

## License

MIT
