import logging
from typing import Optional

import os
from google import genai
from google.genai import types

from state.models import InterviewState, EvaluatorOutput, TurnRecord
from state.defaults import fallback_evaluator_output
from validation.schemas import validate_evaluator_output
from prompts.registry import get_active_version_string
from config.settings import AGENT_CONFIGS
from agents.evaluator.prompts import build_evaluator_user_prompt, EVALUATOR_SYSTEM_PROMPT
from agents.llm_utils import call_with_retry

logger = logging.getLogger(__name__)

# ── Gemini client setup (lazy — key read at first call) ───────────────────────
_client = None
_MODEL = "gemini-flash-lite-latest"


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return _client

HISTORY_WINDOW = 3


def evaluate(state: InterviewState) -> tuple[EvaluatorOutput, bool]:
    turn_index = len(state.turns)
    is_warm_up = (turn_index == 0)

    recent_history = _build_history_window(state.turns)
    prior_topic_scores = _build_prior_topic_scores(state.turns, state.current_topic)

    user_prompt = build_evaluator_user_prompt(
        persona_role=state.context.persona_card.role,
        persona_seniority=state.context.persona_card.seniority.value,
        turn_index=turn_index,
        role=state.context.role,
        focus_area=state.context.focus_area,
        difficulty_level=state.derived.current_difficulty.value,
        is_warm_up_turn=is_warm_up,
        current_topic=state.current_topic,
        question=state.current_question,
        answer=state.current_answer,
        recent_history=recent_history,
        prior_topic_scores=prior_topic_scores,
    )

    logger.info(f"[Evaluator] Turn {turn_index} | topic={state.current_topic}")
    raw = _call_llm(user_prompt)

    if raw is None:
        return fallback_evaluator_output(turn_index, is_warm_up), False

    result, is_valid = validate_evaluator_output(raw, turn_index, is_warm_up)
    return result, is_valid


def _call_llm(user_prompt: str) -> Optional[str]:
    def _invoke():
        response = _get_client().models.generate_content(
            model=_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=EVALUATOR_SYSTEM_PROMPT,
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )
        return response.text if response.text else None
    return call_with_retry(_invoke, "Evaluator")


def _build_history_window(turns: list[TurnRecord]) -> list[dict]:
    window = turns[-HISTORY_WINDOW:] if len(turns) > HISTORY_WINDOW else turns
    return [
        {"turn_index": t.turn_index, "topic": t.topic,
         "question": t.question, "answer": t.answer}
        for t in window
    ]


def _build_prior_topic_scores(turns: list[TurnRecord], current_topic: str) -> dict[int, int]:
    return {
        t.turn_index: t.evaluator_output.scores.technical_depth
        for t in turns if t.topic == current_topic
    }
