"""
AI Mock Interview Coach — FastAPI Backend
Run: uvicorn api:app --reload --port 8000
"""

import os
import uuid
import logging
from typing import Optional
from datetime import datetime, timezone
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
# In-memory report store: report_id → full report dict (includes _turns, report_id)
_reports: dict[str, dict] = {}
# Maps session_id → report_id so we always return the same ID for the same session
_session_to_report: dict[str, str] = {}


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
    persona_name: Optional[str] = None  # Character persona (e.g., "Harvey Specter", "Tyrion Lannister")


class StartResponse(BaseModel):
    session_id: str
    question: str
    topic: str
    phase: str
    turn_count: int
    persona_name: Optional[str] = None  # Active character persona name, if any


class AnswerRequest(BaseModel):
    session_id: str
    answer: str


class AnswerResponse(BaseModel):
    question: Optional[str] = None
    topic: str
    phase: str
    turn_count: int
    is_complete: bool


class EndSessionRequest(BaseModel):
    session_id: str


class EndSessionResponse(BaseModel):
    eligible: bool
    already_complete: bool = False
    substantive_turns: int = 0
    threshold: int = 0
    interview_mode: str = "normal"
    error: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": len(_sessions)}


@app.get("/persona/list")
async def list_personas():
    """Return the built-in persona library — shown in the frontend persona picker."""
    from agents.interviewer.persona_retrieval import _SEED_PROFILES
    personas = []
    for key, profile in _SEED_PROFILES.items():
        personas.append({
            "id": key,
            "name": profile.get("persona_name", key),
            "core_identity": profile.get("core_identity", ""),
            "tone": profile.get("tone", ""),
        })
    return {"personas": personas, "custom_supported": True}


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

    # ── Persona detection & retrieval (runs once per session) ────────────────
    # Priority: explicit persona_name field → auto-detect from interviewer_style → none
    character_persona = None
    persona_candidate: Optional[str] = None

    if req.persona_name and req.persona_name.strip():
        persona_candidate = req.persona_name.strip()
    elif req.interviewer_style and req.interviewer_style.strip():
        style = req.interviewer_style.strip()
        try:
            from agents.interviewer.persona_retrieval import _find_seed, _looks_like_entity
            if _find_seed(style) or _looks_like_entity(style):
                persona_candidate = style
                logger.info(f"[Persona] Auto-detected entity from style: {style!r}")
        except Exception:
            pass  # non-fatal — fall back to plain style

    if persona_candidate:
        try:
            from agents.interviewer.persona_retrieval import retrieve_persona_profile
            import asyncio
            character_persona = await asyncio.to_thread(
                retrieve_persona_profile,
                persona_candidate,
                req.focus_area,
                req.role,
            )
            if character_persona:
                logger.info(
                    f"[Persona] Profile ready: {character_persona.get('persona_name', persona_candidate)!r} "
                    f"for session {session_id[:8]}"
                )
        except Exception as e:
            logger.warning(f"[Persona] Retrieval failed (non-fatal): {e}")
            character_persona = None

    try:
        session = InterviewSession.start(context, character_persona=character_persona)
        _sessions[session_id] = session
    except Exception as e:
        logger.error(f"Session start failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start session: {e}")

    active_persona_name = character_persona.get("persona_name") if character_persona else None
    return StartResponse(
        session_id=session_id,
        question=session.current_question(),
        topic=session.current_topic(),
        phase=session.current_phase(),
        turn_count=session.turn_count(),
        persona_name=active_persona_name,
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


@app.post("/session/end", response_model=EndSessionResponse)
async def end_session_early(req: EndSessionRequest):
    """
    End the interview early and attempt to generate a report.
    Returns 'eligible: false' with counts if there is not enough transcript depth.
    Returns 'eligible: true' once the report has been generated and stored.
    """
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        result = session.end_early()
    except Exception as e:
        logger.error(f"Early termination failed for {req.session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Early termination failed: {e}")

    return EndSessionResponse(**result)


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

    # Store in _reports for share link + PDF download
    report_id = _store_report(session_id, report)
    report["report_id"] = report_id
    # Update stored copy so the embedded report_id is correct
    _reports[report_id] = report

    return report


def _store_report(session_id: str, report: dict) -> str:
    """
    Persist a completed report in the in-memory store and return the report_id.
    Guarantees the same session always gets the same report_id (idempotent).
    """
    if session_id in _session_to_report:
        report_id = _session_to_report[session_id]
        _reports[report_id] = report  # Refresh stored copy with latest data
        return report_id
    report_id = str(uuid.uuid4())
    _reports[report_id] = report
    _session_to_report[session_id] = report_id
    logger.info(f"[Report] Stored report_id={report_id} for session={session_id[:8]}")
    return report_id


@app.get("/report/{report_id}")
async def get_report_by_id(report_id: str):
    """
    Retrieve a stored report by its report_id (for shareable links).
    The report_id is returned in the /session/report response.
    """
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found or expired")
    return report


@app.get("/session/report/pdf")
async def download_report_pdf(session_id: str):
    """
    Generate and return a PDF version of the interview report.
    The session must be complete and the report must have been generated
    (i.e. /session/report was called at least once for this session).
    """
    # Find the stored report for this session (fast O(1) lookup)
    report_id_for_session = _session_to_report.get(session_id)
    report = _reports.get(report_id_for_session) if report_id_for_session else None

    if not report:
        # Try generating it on-demand (session must be complete)
        session = _sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not session.is_complete():
            raise HTTPException(status_code=400, detail="Interview not yet complete")
        raw_report = session.get_report()
        if not raw_report:
            raise HTTPException(status_code=500, detail="Report generation failed")
        turns = session.get_turn_log()
        raw_report["_turns"] = [
            {
                "turn_index": t.get("turn_index", 0) if isinstance(t, dict) else t.turn_index,
                "topic": t.get("topic", "") if isinstance(t, dict) else t.topic,
                "question": t.get("question", "") if isinstance(t, dict) else t.question,
                "answer": t.get("answer", "") if isinstance(t, dict) else t.answer,
            }
            for t in turns
        ]
        report = raw_report
        _store_report(session_id, report)

    try:
        from agents.coach.pdf_generator import generate_pdf
        pdf_bytes = generate_pdf(report)
    except Exception as e:
        logger.error(f"PDF generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="PDF generation failed — fpdf2 may not be installed")

    role = (report.get("role") or "interview").replace(" ", "_")
    filename = f"report_{role}_{session_id[:8]}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/report/{report_id}/pdf")
async def download_report_pdf_by_id(report_id: str):
    """
    Generate and return a PDF version of a stored report by report_id.
    Useful for share links where the session may no longer be active.
    """
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found or expired")

    try:
        from agents.coach.pdf_generator import generate_pdf
        pdf_bytes = generate_pdf(report)
    except Exception as e:
        logger.error(f"PDF generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="PDF generation failed — fpdf2 may not be installed")

    role = (report.get("role") or "interview").replace(" ", "_")
    filename = f"report_{role}_{report_id[:8]}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
