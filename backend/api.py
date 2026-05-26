"""
AI Mock Interview Coach — FastAPI Backend
Run: uvicorn api:app --reload --port 8000
"""

import os
import uuid
import logging
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from state.models import ImmutableContext, PersonaCard
from state.enums import DifficultyLevel
from orchestrator.session import InterviewSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Mock Interview Coach", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessions: dict[str, InterviewSession] = {}


# ── Request / Response Models ──────────────────────────────────────────────────

class StartRequest(BaseModel):
    role: str = "Product Manager"
    focus_area: str = "product strategy and execution"
    candidate_background: str = "3+ years product management experience"
    difficulty: str = "mid"
    topics: list[str] = ["product vision", "prioritization", "metrics and analytics", "stakeholder management", "past launches"]
    target_turns: int = 6
    interviewer_role: str = "Director of Product"
    interviewer_seniority: str = "director"
    interviewer_yoe: int = 15
    interviewer_style: str = "Curious and direct. Focuses on reasoning behind decisions, not just outcomes. Asks one question at a time."
    interview_mode: str = "normal"  # "normal" | "grill"


class StartResponse(BaseModel):
    session_id: str
    question: str
    topic: str
    phase: str
    turn_count: int


class AnswerRequest(BaseModel):
    session_id: str
    answer: str


class AnswerResponse(BaseModel):
    question: Optional[str] = None
    topic: str
    phase: str
    turn_count: int
    is_complete: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": len(_sessions)}


@app.post("/session/start", response_model=StartResponse)
async def start_session(req: StartRequest):
    try:
        difficulty = DifficultyLevel(req.difficulty)
    except ValueError:
        difficulty = DifficultyLevel.MID

    try:
        int_seniority = DifficultyLevel(req.interviewer_seniority)
    except ValueError:
        int_seniority = DifficultyLevel.DIRECTOR
        
    ranks = {
        DifficultyLevel.JUNIOR: 1,
        DifficultyLevel.MID: 2,
        DifficultyLevel.SENIOR: 3,
        DifficultyLevel.STAFF: 4,
        DifficultyLevel.PRINCIPAL: 5,
        DifficultyLevel.DIRECTOR: 6,
    }
    
    if ranks.get(int_seniority, 6) <= ranks.get(difficulty, 2):
        raise HTTPException(
            status_code=400, 
            detail=f"Interviewer seniority ({int_seniority.value}) must be strictly higher than candidate target seniority ({difficulty.value})."
        )

    session_id = str(uuid.uuid4())

    # Grill Mode enforces a minimum of 10 turns for a genuinely long interview
    interview_mode = req.interview_mode if req.interview_mode in ("normal", "grill") else "normal"
    effective_turns = req.target_turns
    if interview_mode == "grill":
        effective_turns = max(effective_turns, 10)
    # Hard cap for the model field (le=14)
    effective_turns = min(effective_turns, 14)

    context = ImmutableContext(
        session_id=session_id,
        role=req.role,
        focus_area=req.focus_area,
        candidate_background=req.candidate_background,
        difficulty_target=difficulty,
        target_turn_count=effective_turns,
        topic_list=req.topics,
        persona_card=PersonaCard(
            role=req.interviewer_role,
            seniority=int_seniority,
            years_of_experience=req.interviewer_yoe,
            domain=req.focus_area,
            style=req.interviewer_style
        ),
        interview_mode=interview_mode,
    )

    try:
        session = InterviewSession.start(context)
        _sessions[session_id] = session
    except Exception as e:
        logger.error(f"Session start failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start session: {e}")

    return StartResponse(
        session_id=session_id,
        question=session.current_question(),
        topic=session.current_topic(),
        phase=session.current_phase(),
        turn_count=session.turn_count(),
    )


@app.post("/session/answer", response_model=AnswerResponse)
async def submit_answer(req: AnswerRequest):
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.is_complete():
        return AnswerResponse(question=None, topic="", phase="reporting",
                              turn_count=session.turn_count(), is_complete=True)

    try:
        next_q = session.submit_answer(req.answer)
    except Exception as e:
        logger.error(f"Answer submission failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Answer processing failed: {e}")

    return AnswerResponse(
        question=next_q,
        topic=session.current_topic(),
        phase=session.current_phase(),
        turn_count=session.turn_count(),
        is_complete=session.is_complete(),
    )


@app.get("/session/report")
async def get_report(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.is_complete():
        raise HTTPException(status_code=400, detail="Interview not yet complete")

    report = session.get_report()
    if not report:
        raise HTTPException(status_code=500, detail="Report generation failed")

    # Attach serialized turn log for transcript panel
    turns = session.get_turn_log()
    report["_turns"] = [
        {
            "turn_index": t.get("turn_index", 0) if isinstance(t, dict) else t.turn_index,
            "topic": t.get("topic", "") if isinstance(t, dict) else t.topic,
            "question": t.get("question", "") if isinstance(t, dict) else t.question,
            "answer": t.get("answer", "") if isinstance(t, dict) else t.answer,
        }
        for t in turns
    ]
    return report


# ── Voice (ElevenLabs proxy) ───────────────────────────────────────────────

_ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"  # Rachel


class VoiceRequest(BaseModel):
    text: str


@app.get("/voice/status")
async def voice_status():
    """Let the frontend know whether voice is configured server-side."""
    available = bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())
    return {"available": available}


@app.post("/voice/speak")
async def voice_speak(req: VoiceRequest):
    """
    Proxy text-to-speech via ElevenLabs using a server-side API key.
    Returns audio/mpeg bytes on success, 503 if voice is not configured.
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Voice not configured on this server.")

    if not req.text.strip():
        raise HTTPException(status_code=400, detail="No text provided.")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{_ELEVENLABS_VOICE_ID}"
    payload = {
        "text": req.text,
        "model_id": "eleven_turbo_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.RequestError as e:
        logger.warning(f"[Voice] ElevenLabs request failed: {e}")
        raise HTTPException(status_code=502, detail="Voice service unreachable.")

    if not resp.is_success:
        logger.warning(f"[Voice] ElevenLabs returned {resp.status_code}")
        raise HTTPException(status_code=502, detail="Voice service error.")

    return Response(content=resp.content, media_type="audio/mpeg")
