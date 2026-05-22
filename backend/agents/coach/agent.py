import json
import logging
from datetime import datetime, timezone
from typing import Optional

import os
from google import genai
from google.genai import types

from state.models import InterviewState, TurnRecord, AggregateScores
from state.enums import ScoreTrajectory, TopicStatus, InterviewPhase
from state.defaults import WARM_UP_SCORE_WEIGHT, NORMAL_SCORE_WEIGHT
from report.models import (
    CoachReport, ScoreSummary, FeedbackPoint,
    TurnEvidence, TopicCoverageSummary,
)
from prompts.registry import get_active_version_string
from config.settings import AGENT_CONFIGS
from agents.coach.prompts import (
    COACH_ANALYSIS_SYSTEM_PROMPT,
    COACH_REPORT_SYSTEM_PROMPT,
    build_analysis_user_prompt,
    build_report_user_prompt,
)
from validation.schemas import _extract_json
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


def generate_report(state: InterviewState) -> CoachReport:
    logger.info(f"[Coach] Generating report | {len(state.turns)} turns")
    
    # Exclude turns where phase is CLOSING (producing substantive_turns)
    substantive_turns = [t for t in state.turns if t.phase != InterviewPhase.CLOSING]
    logger.info(f"[Coach] Filtered to {len(substantive_turns)} substantive turns")
    
    turns_data = _serialize_turns(substantive_turns)
    analysis_str, analysis_dict = _run_analysis(state, substantive_turns, turns_data)
    return _run_report(state, substantive_turns, turns_data, analysis_str, analysis_dict)


def _run_analysis(state: InterviewState, substantive_turns: list[TurnRecord], turns_data: list[dict]) -> tuple[str, dict]:
    ctx = state.context
    user_prompt = build_analysis_user_prompt(
        role=ctx.role,
        focus_area=ctx.focus_area,
        difficulty_target=ctx.difficulty_target.value,
        turns_data=turns_data,
        warm_up_weight=ctx.warm_up_score_weight,
    )
    raw = _call_llm(COACH_ANALYSIS_SYSTEM_PROMPT, user_prompt)
    if raw is None:
        empty = _empty_analysis(turns_data)
        return json.dumps(empty), empty
    parsed = _extract_json(raw)
    if parsed is None:
        empty = _empty_analysis(turns_data)
        return json.dumps(empty), empty
    return json.dumps(parsed, indent=2), parsed


def _run_report(
    state: InterviewState,
    substantive_turns: list[TurnRecord],
    turns_data: list[dict],
    analysis_str: str,
    analysis_dict: dict,
) -> CoachReport:
    ctx = state.context
    user_prompt = build_report_user_prompt(
        session_id=ctx.session_id,
        role=ctx.role,
        focus_area=ctx.focus_area,
        total_turns=len(substantive_turns),
        analysis_json=analysis_str,
        turns_data=turns_data,
    )
    raw = _call_llm(COACH_REPORT_SYSTEM_PROMPT, user_prompt)
    if raw is None:
        return _fallback_report(state, substantive_turns, analysis_dict)
    parsed = _extract_json(raw)
    if parsed is None:
        return _fallback_report(state, substantive_turns, analysis_dict)
    parsed = _inject_deterministic(parsed, state, substantive_turns)
    try:
        return CoachReport(**parsed)
    except Exception as e:
        logger.warning(f"[Coach] Schema validation failed: {e}")
        return _fallback_report(state, substantive_turns, analysis_dict)


def _call_llm(system_instruction: str, user_prompt: str) -> Optional[str]:
    def _invoke():
        response = _get_client().models.generate_content(
            model=_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3,
                max_output_tokens=2048,
            ),
        )
        return response.text if response.text else None
    return call_with_retry(_invoke, "Coach")


def _inject_deterministic(parsed: dict, state: InterviewState, substantive_turns: list[TurnRecord]) -> dict:
    ctx = state.context
    parsed["session_id"] = ctx.session_id
    parsed["role"] = ctx.role
    parsed["focus_area"] = ctx.focus_area
    parsed["total_turns"] = len(substantive_turns)
    parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
    parsed["prompt_version_coach"] = get_active_version_string("coach")
    parsed["interview_duration_approx"] = f"~{len(substantive_turns) * 2} minutes"

    agg = _compute_scores(substantive_turns, ctx.warm_up_score_weight)
    strongest, weakest = _extremes(agg)
    if "score_summary" not in parsed or not isinstance(parsed.get("score_summary"), dict):
        parsed["score_summary"] = {}
    parsed["score_summary"]["scores"] = agg.model_dump()
    parsed["score_summary"]["trajectory"] = state.derived.score_trajectory.value
    parsed["score_summary"]["strongest_dimension"] = strongest
    parsed["score_summary"]["weakest_dimension"] = weakest
    parsed["topic_coverage"] = _build_coverage(state, substantive_turns)
    return parsed


def _compute_scores(turns: list[TurnRecord], warm_up_weight: float) -> AggregateScores:
    if not turns:
        return AggregateScores()
    sums = {
        "technical_depth": 0.0, "communication_quality": 0.0,
        "epistemic_calibration": 0.0, "groundedness": 0.0,
    }
    total_w = 0.0
    for t in turns:
        w = warm_up_weight if t.turn_index == 0 else NORMAL_SCORE_WEIGHT
        s = t.evaluator_output.scores
        sums["technical_depth"] += s.technical_depth * w
        sums["communication_quality"] += s.communication_quality * w
        sums["epistemic_calibration"] += s.epistemic_calibration * w
        sums["groundedness"] += s.groundedness * w
        total_w += w
    if total_w == 0:
        return AggregateScores()
    return AggregateScores(**{k: round(v / total_w, 2) for k, v in sums.items()})


def _extremes(scores: AggregateScores) -> tuple[str, str]:
    d = scores.model_dump()
    if not d:
        return "", ""
    vals = list(d.values())
    max_val = max(vals)
    min_val = min(vals)
    
    # If the difference between max and min is small (e.g. <= 0.3), return empty string for both (balanced profile)
    if max_val - min_val <= 0.3:
        return "", ""
        
    strongest = max(d, key=d.get)
    weakest = min(d, key=d.get)
    
    # Ensure strongest never equals weakest
    if strongest == weakest:
        sorted_keys = sorted(d.keys(), key=lambda k: d[k])
        strongest = sorted_keys[-1]
        weakest = sorted_keys[0]
        if strongest == weakest:
            return "", ""
            
    return strongest, weakest


def _build_coverage(state: InterviewState, substantive_turns: list[TurnRecord]) -> list[dict]:
    result = []
    for topic, status in state.derived.topic_coverage.items():
        if topic == "closing":
            continue
        topic_turns = [t for t in substantive_turns if t.topic == topic]
        peak = max(
            (t.evaluator_output.scores.technical_depth for t in topic_turns),
            default=None,
        )
        result.append({
            "topic": topic,
            "status": status.value if hasattr(status, "value") else str(status),
            "turns_spent": len(topic_turns),
            "peak_depth_score": peak,
            "summary": (
                f"Covered in {len(topic_turns)} turn(s)."
                if topic_turns else f"{topic} not covered."
            ),
        })
    return result


def _serialize_turns(turns: list[TurnRecord]) -> list[dict]:
    result = []
    for t in turns:
        ev = t.evaluator_output
        result.append({
            "turn_index": t.turn_index, "topic": t.topic,
            "question": t.question, "answer": t.answer,
            "is_warm_up": ev.is_warm_up_turn,
            "scores": ev.scores.model_dump(),
            "flags": ev.flags.model_dump(),
            "follow_up_signals": ev.follow_up_signals,
            "reasoning": ev.reasoning,
            "cross_turn": ev.cross_turn.model_dump(),
            "unsupported_claims": ev.unsupported_claims_detail,
            "evaluation_confidence": ev.evaluation_confidence.value,
        })
    return result


def _fallback_report(state: InterviewState, substantive_turns: list[TurnRecord], _: dict) -> CoachReport:
    ctx = state.context
    agg = _compute_scores(substantive_turns, ctx.warm_up_score_weight)
    strongest, weakest = _extremes(agg)
    scored = [t for t in substantive_turns if not t.evaluator_output.is_warm_up_turn]

    def combined(t: TurnRecord) -> float:
        s = t.evaluator_output.scores
        return s.technical_depth + s.communication_quality + s.groundedness

    best = max(scored, key=combined) if scored else (substantive_turns[0] if substantive_turns else None)
    weak = min(scored, key=combined) if scored else best

    def make_fp(obs: str, turn, sug: str) -> FeedbackPoint:
        ev = [TurnEvidence(
            turn_index=turn.turn_index if turn else 0,
            excerpt=f"Response on {turn.topic if turn else 'unknown'}.",
            relevance="Selected based on evaluator scores.",
        )] if turn else [TurnEvidence(
            turn_index=0, excerpt="[Fallback]", relevance="[Fallback report]"
        )]
        return FeedbackPoint(observation=obs, evidence=ev, suggestion=sug)

    return CoachReport(
        session_id=ctx.session_id, role=ctx.role, focus_area=ctx.focus_area,
        total_turns=len(substantive_turns),
        interview_duration_approx=f"~{len(substantive_turns) * 2} minutes",
        overall_summary=(
            f"[Fallback report] Interview completed with {len(substantive_turns)} turns. "
            f"Strongest: {strongest.replace('_', ' ') if strongest else 'general'}. Growth area: {weakest.replace('_', ' ') if weakest else 'general'}."
        ),
        score_summary=ScoreSummary(
            scores=agg, trajectory=state.derived.score_trajectory,
            strongest_dimension=strongest, weakest_dimension=weakest,
        ),
        strengths=[make_fp(
            f"Strongest performance in {strongest.replace('_', ' ') if strongest else 'general'}.", best,
            f"Continue demonstrating {strongest.replace('_', ' ') if strongest else 'strong engineering fundamentals'} in interviews.",
        )],
        improvement_areas=[make_fp(
            f"Growth opportunity in {weakest.replace('_', ' ') if weakest else 'general'}.", weak,
            f"Focus practice on {weakest.replace('_', ' ') if weakest else 'grounding design choices'} with specific examples.",
        )],
        communication_feedback=make_fp(
            "Communication quality assessed from transcript.", best,
            "Review transcript and focus on answer structure.",
        ),
        technical_feedback=make_fp(
            "Technical depth assessed from evaluator scores.", best,
            "Practice grounding technical answers in specific examples.",
        ),
        practice_recommendations=[
            f"Review your answers on {ctx.focus_area} and identify where to add more specifics.",
            "Practice explaining one technical concept verbally in 2 minutes with a concrete example.",
            "For each project you reference, prepare: problem solved, what you built, one lesson learned.",
        ],
        topic_coverage=_build_coverage(state, substantive_turns),
        transcript_highlights=[TurnEvidence(
            turn_index=best.turn_index if best else 0,
            excerpt=f"Best response on {best.topic if best else 'unknown'}.",
            relevance="Highest combined evaluator score.",
        )],
        generated_at=datetime.now(timezone.utc).isoformat(),
        prompt_version_coach=get_active_version_string("coach"),
    )


def _empty_analysis(turns_data: list[dict]) -> dict:
    return {
        "total_scored_turns": len([t for t in turns_data if not t.get("is_warm_up")]),
        "dimension_analysis": {},
        "patterns": {
            "consistent_strengths": [], "consistent_weaknesses": [],
            "flags_observed": {}, "has_contradiction": False,
            "contradiction_detail": None, "groundedness_gap": False,
            "score_trajectory": "insufficient_data",
        },
        "notable_moments": {
            "best_answer": None, "weakest_answer": None,
            "most_honest_moment": None, "strongest_recovery": None,
        },
        "topic_performance": [],
    }
