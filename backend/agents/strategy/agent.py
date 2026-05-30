import logging
from typing import Optional

import os
from google import genai
from google.genai import types

from state.models import InterviewState, InterviewPlan, StrategyDecision, EvaluatorToStrategy, GuardrailResult, safe_rehydrate
from state.enums import InterviewPhase
from state.defaults import fallback_strategy_decision
from validation.schemas import validate_strategy_decision
from prompts.registry import get_active_version_string
from config.settings import AGENT_CONFIGS
from agents.strategy.prompts import STRATEGY_SYSTEM_PROMPT, build_strategy_user_prompt
from agents.strategy.planner import build_plan_context_block
from orchestrator.guardrails import apply_all_guardrails, GuardrailResult
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


def decide(
    state: InterviewState,
    plan: Optional[InterviewPlan] = None,
    retrieved_context=None,
) -> tuple[StrategyDecision, GuardrailResult]:
    mailbox: Optional[EvaluatorToStrategy] = state.mailboxes.evaluator_to_strategy
    if mailbox is None:
        raise ValueError("Strategy Agent called without evaluator mailbox populated.")

    turn_count = len(state.turns)
    logger.info(f"[Strategy] Turn {turn_count} | topic={state.current_topic}")

    # Use the explicitly passed plan (with reflection already applied) or fall back to state's plan
    effective_plan = plan if plan is not None else state.interview_plan
    user_prompt = _build_prompt(state, mailbox, turn_count, plan=effective_plan, retrieved_context=retrieved_context)
    raw = _call_llm(user_prompt)

    if raw is None:
        raw_decision = fallback_strategy_decision(state.current_topic, state.current_phase)
    else:
        raw_decision, is_valid = validate_strategy_decision(
            raw, state.current_topic, state.current_phase
        )
        if not is_valid:
            logger.warning(f"[Strategy] Validation failed at turn {turn_count}")

    raw_evaluator = getattr(state, "_staged_evaluator_output", None) or (state.turns[-1].evaluator_output if state.turns else None)
    
    from state.models import EvaluatorOutput
    current_evaluator = safe_rehydrate(raw_evaluator, EvaluatorOutput)

    if current_evaluator is None:
        guardrail_result = GuardrailResult(
            decision=raw_decision, overrides_applied=[], was_overridden=False
        )
    else:
        guardrail_result = apply_all_guardrails(
            decision=raw_decision,
            derived=state.derived,
            evaluator=current_evaluator,
            target_turn_count=state.context.target_turn_count,
            turns=state.turns,
        )

    logger.info(
        f"[Strategy] → {guardrail_result.decision.next_action.value} "
        f"| topic={guardrail_result.decision.target_topic}"
    )
    return guardrail_result.decision, guardrail_result


def _call_llm(user_prompt: str) -> Optional[str]:
    def _invoke():
        response = _get_client().models.generate_content(
            model=_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=STRATEGY_SYSTEM_PROMPT,
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )
        return response.text if response.text else None
    return call_with_retry(_invoke, "Strategy")


def _build_prompt(
    state: InterviewState,
    mailbox: EvaluatorToStrategy,
    turn_count: int,
    plan: Optional[InterviewPlan] = None,
    retrieved_context=None,
) -> str:
    derived = state.derived
    ctx = state.context
    last_action = next(
        (t.strategy_decision.next_action.value
         for t in reversed(state.turns)
         if t.topic == state.current_topic),
        None,
    )
    ct = mailbox.cross_turn
    cross_summary = "No contradictions detected."
    if not ct.consistent:
        cross_summary = (
            f"Contradiction with turn {ct.contradicts_turn_index}: "
            f"{ct.contradiction_description or 'details unavailable'}"
        )
    if ct.recycled_example:
        cross_summary += " | Recycled example detected."

    # Use current turn's evaluator output (staged), falling back to last appended turn
    from state.models import EvaluatorOutput as _EO
    _staged = getattr(state, "_staged_evaluator_output", None)
    _current_ev = safe_rehydrate(_staged, _EO)
    scores = {}
    if _current_ev:
        scores = _current_ev.scores.model_dump()
    elif state.turns:
        scores = state.turns[-1].evaluator_output.scores.model_dump()

    recent_history = [
        {"turn_index": t.turn_index, "topic": t.topic, "question": t.question, "answer": t.answer}
        for t in state.turns
    ]

    plan_context_block = build_plan_context_block(plan) if plan and plan.initialized else ""

    return build_strategy_user_prompt(
        persona_role=ctx.persona_card.role,
        persona_seniority=ctx.persona_card.seniority.value,
        role=ctx.role,
        focus_area=ctx.focus_area,
        difficulty_target=ctx.difficulty_target.value,
        current_difficulty=derived.current_difficulty.value,
        current_phase=state.current_phase.value,
        current_topic=state.current_topic,
        turn_count=turn_count,
        target_turn_count=ctx.target_turn_count,
        coverage_breadth_pct=derived.coverage_breadth_pct,
        topics_remaining=derived.topics_remaining,
        topic_coverage={k: (v.value if hasattr(v, "value") else str(v)) for k, v in derived.topic_coverage.items()},
        depth_ceilings=derived.depth_ceilings,
        consecutive_actions_on_topic=derived.consecutive_actions_on_topic,
        last_action=last_action,
        evaluator_flags=mailbox.flags.model_dump(),
        evaluator_scores=scores,
        follow_up_signals=mailbox.follow_up_signals,
        evaluation_confidence=mailbox.evaluation_confidence.value,
        cross_turn_summary=cross_summary,
        score_trajectory=derived.score_trajectory.value,
        last_question=state.current_question,
        last_answer=state.current_answer,
        recent_history=recent_history,
        interview_mode=getattr(ctx, "interview_mode", "normal"),
        plan_context_block=plan_context_block,
        retrieved_context=retrieved_context,
    )
