import logging
import re
from typing import Optional

import os
from google import genai
from google.genai import types

from state.models import InterviewState, StrategyToInterviewer, TurnRecord
from state.enums import InterviewPhase, NextAction
from agents.interviewer.prompts import (
    build_system_prompt,
    build_opening_prompt,
    build_closing_prompt,
    build_chat_task_directive,
)
from agents.llm_utils import call_with_retry

logger = logging.getLogger(__name__)

# ── Gemini client setup (lazy — key read at first call) ───────────────────────
_client = None
_MODEL = "gemini-flash-lite-latest"

DIALOGUE_WINDOW = 6  # how many prior turns to include in chat history


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def ask(state: InterviewState) -> str:
    mailbox: Optional[StrategyToInterviewer] = state.mailboxes.strategy_to_interviewer
    turn_index = len(state.turns)
    system_prompt = _build_system_prompt(state)

    # ── Opening turn ──────────────────────────────────────────────────────────
    if mailbox is None or turn_index == 0:
        user_prompt = build_opening_prompt(
            persona_role=state.context.persona_card.role,
            persona_seniority=state.context.persona_card.seniority.value,
            persona_yoe=state.context.persona_card.years_of_experience,
            focus_area=state.context.focus_area,
            candidate_background=state.context.candidate_background,
            target_turn_count=state.context.target_turn_count,
        )
        raw = _call_single(system_prompt, user_prompt)
        if raw is None:
            return _fallback(state.current_topic, InterviewPhase.OPENING, [])
        return _post_process(raw)

    # ── Closing turn ──────────────────────────────────────────────────────────
    if (mailbox.next_action == NextAction.WRAP_UP
            or mailbox.interview_phase == InterviewPhase.CLOSING):
        recent = _fmt_history_text(state.turns)
        user_prompt = build_closing_prompt(
            role=state.context.role,
            turn_count=turn_index,
            recent_history=recent,
        )
        raw = _call_single(system_prompt, user_prompt)
        if raw is None:
            return _fallback(state.current_topic, InterviewPhase.CLOSING, [])
        return _post_process(raw)

    # ── Follow-up turns — MULTI-TURN CHAT ────────────────────────────────────
    contents = _build_chat_contents(state, mailbox)
    raw = _call_chat(system_prompt, contents)
    if raw is None:
        prev_questions = [t.question for t in state.turns]
        return _fallback(state.current_topic, InterviewPhase.QUESTIONING, prev_questions)
    return _post_process(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Multi-turn chat content builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_chat_contents(
    state: InterviewState,
    mailbox: StrategyToInterviewer,
) -> list:
    """
    Structure the conversation as alternating user/model turns so Gemini
    responds TO the candidate's last answer rather than ignoring it.

    Turn mapping:
      model = interviewer (what we're generating)
      user  = candidate answers + task directives
    """
    ctx = state.context
    turns = state.turns
    window = turns[-DIALOGUE_WINDOW:] if len(turns) > DIALOGUE_WINDOW else turns

    contents = []

    # ── Turn 0: context preamble (must be a user turn) ───────────────────────
    preamble = (
        f"We are conducting a {ctx.role} interview focused on {ctx.focus_area}. "
        f"Candidate background: {ctx.candidate_background}. "
        f"You are the interviewer. Begin."
    )
    contents.append(types.Content(role="user", parts=[types.Part(text=preamble)]))

    if not window:
        # No history at all — shouldn't happen for follow-ups, but safe fallback
        return contents

    # ── Interleave prior turns (model=interviewer, user=candidate) ────────────
    for i, t in enumerate(window):
        # Interviewer's question (model turn)
        contents.append(types.Content(role="model", parts=[types.Part(text=t.question)]))

        # Candidate's answer (user turn)
        # For all turns EXCEPT the last, just the raw answer
        if i < len(window) - 1:
            contents.append(types.Content(role="user", parts=[types.Part(text=t.answer)]))

    # ── Last candidate answer + task directive (user turn) ───────────────────
    last_turn = window[-1]

    # Gather signals the evaluator extracted from the last answer
    signals: list[str] = []
    try:
        signals = last_turn.evaluator_output.follow_up_signals or []
    except Exception:
        pass

    is_pivot = mailbox.next_action == NextAction.PIVOT
    prev_topic = next(
        (t.topic for t in reversed(state.turns) if t.topic != mailbox.target_topic),
        None,
    )
    previously_asked = [f"[{t.topic}] {t.question}" for t in state.turns]

    directive = build_chat_task_directive(
        current_topic=mailbox.target_topic,
        action=mailbox.next_action.value,
        follow_up_intent=mailbox.follow_up_intent.value,
        reasoning=mailbox.reasoning or "",
        difficulty_level=state.derived.current_difficulty.value,
        previously_asked=previously_asked,
        signals=signals,
        is_pivot=is_pivot,
        previous_topic=prev_topic if is_pivot else None,
    )

    last_user_content = f"{last_turn.answer}\n\n{directive}"
    contents.append(types.Content(role="user", parts=[types.Part(text=last_user_content)]))

    return contents


# ─────────────────────────────────────────────────────────────────────────────
# LLM call wrappers
# ─────────────────────────────────────────────────────────────────────────────

def _call_single(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Single-shot generation (opening / closing)."""
    def _invoke():
        response = _get_client().models.generate_content(
            model=_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7,
                max_output_tokens=512,
            ),
        )
        return response.text if response.text else None
    return call_with_retry(_invoke, "Interviewer")


def _call_chat(system_prompt: str, contents: list) -> Optional[str]:
    """Multi-turn chat generation (all follow-up questions)."""
    def _invoke():
        response = _get_client().models.generate_content(
            model=_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7,
                max_output_tokens=512,
            ),
        )
        return response.text if response.text else None
    return call_with_retry(_invoke, "Interviewer")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_system_prompt(state: InterviewState) -> str:
    ctx = state.context
    return build_system_prompt(
        persona_role=ctx.persona_card.role,
        persona_seniority=ctx.persona_card.seniority.value,
        persona_yoe=ctx.persona_card.years_of_experience,
        persona_style=ctx.persona_card.style,
        focus_area=ctx.focus_area,
    )


def _fmt_history_text(turns: list[TurnRecord], window: int = DIALOGUE_WINDOW) -> str:
    """Plain-text history for closing prompt."""
    recent = turns[-window:] if len(turns) > window else turns
    lines = []
    for t in recent:
        lines.append(f"Interviewer: {t.question}")
        lines.append(f"Candidate: {t.answer}")
    return "\n\n".join(lines) if lines else "(No prior dialogue)"


def _post_process(raw: str) -> str:
    if not raw:
        return "Let's continue — could you tell me more about that?"

    text = raw.strip()

    # Strip markdown formatting
    text = re.sub(r'\*\*[^*]+\*\*', lambda m: m.group(0)[2:-2], text)  # bold → plain
    text = re.sub(r'\*[^*]+\*', lambda m: m.group(0)[1:-1], text)       # italic → plain
    text = re.sub(r'__[^_]+__', lambda m: m.group(0)[2:-2], text)

    # Strip code fences
    if "```" in text:
        text = "\n".join(
            l for l in text.split("\n") if not l.strip().startswith("```")
        ).strip()

    # Strip leading meta-labels the model sometimes outputs
    text = re.sub(r'^(PART\s*\d[\s\-—:]*|Acknowledgment[\s:]*|Question[\s:]*)', '', text, flags=re.IGNORECASE).strip()

    if not text:
        return "Could you tell me a bit more about that?"

    # Keep everything up to and including the LAST "?" — preserves
    # "ack sentence. question?" structure while dropping stray trailing text.
    if "?" in text:
        text = text[:text.rfind("?") + 1].strip()
    else:
        if text.endswith("-") or len(text.split()) < 4:
            return "Could you elaborate on that?"
        text = text.rstrip(".- ") + " — could you tell me more about that?"

    return text


def _fallback(topic: str, phase: InterviewPhase, prev_questions: list[str] = None) -> str:
    if prev_questions is None:
        prev_questions = []

    fallbacks = {
        InterviewPhase.OPENING: (
            "Thanks for joining — could you give me a quick overview "
            "of your background and what drew you to this role?"
        ),
        InterviewPhase.QUESTIONING: (
            f"Could you walk me through a specific situation where you dealt with {topic}?"
        ),
        InterviewPhase.CLOSING: (
            "We're wrapping up — do you have any questions for me?"
        ),
        InterviewPhase.REPORTING: (
            "Thank you — is there anything you'd like to add?"
        ),
    }

    primary = fallbacks.get(phase, fallbacks[InterviewPhase.QUESTIONING])
    if primary in prev_questions and phase == InterviewPhase.QUESTIONING:
        return f"What was the hardest decision you had to make around {topic}, and why?"
    return primary
