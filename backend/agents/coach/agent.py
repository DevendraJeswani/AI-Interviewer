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
    # Compute severity ahead of report generation so the prompt can calibrate language
    agg_preview = _compute_scores(substantive_turns, ctx.warm_up_score_weight)
    _, weakest_key_preview = _extremes(agg_preview)
    severity = _weakness_severity(agg_preview, weakest_key_preview)
    dim_labels_preview = _role_dimension_labels(ctx.role)
    weakest_label_preview = dim_labels_preview.get(weakest_key_preview, weakest_key_preview) if weakest_key_preview else ""

    user_prompt = build_report_user_prompt(
        session_id=ctx.session_id,
        role=ctx.role,
        focus_area=ctx.focus_area,
        total_turns=len(substantive_turns),
        analysis_json=analysis_str,
        turns_data=turns_data,
        weakness_severity=severity,
        weakest_label=weakest_label_preview,
        difficulty_target=ctx.difficulty_target.value,
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

    # Compute scores from transcript
    agg = _compute_scores(substantive_turns, ctx.warm_up_score_weight)
    strongest_key, weakest_key = _extremes(agg)  # raw dimension keys ("technical_depth", …)

    # Map to role-appropriate display labels
    dim_labels = _role_dimension_labels(ctx.role)
    parsed["dimension_labels"] = dim_labels

    strongest_label = dim_labels.get(strongest_key, strongest_key) if strongest_key else ""
    weakest_label   = dim_labels.get(weakest_key,   weakest_key)   if weakest_key   else ""

    if "score_summary" not in parsed or not isinstance(parsed.get("score_summary"), dict):
        parsed["score_summary"] = {}
    parsed["score_summary"]["scores"] = agg.model_dump()
    parsed["score_summary"]["trajectory"] = state.derived.score_trajectory.value
    # Store the human-readable label so the frontend can display it directly
    parsed["score_summary"]["strongest_dimension"] = strongest_label
    parsed["score_summary"]["weakest_dimension"]   = weakest_label
    parsed["weakness_severity"] = _weakness_severity(agg, weakest_key)
    parsed["overall_score"] = _compute_overall_score(
        substantive_turns, ctx.warm_up_score_weight, state.derived.score_trajectory
    )
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


def _role_dimension_labels(role: str) -> dict[str, str]:
    """
    Returns role-appropriate display labels for the four scoring dimensions.
    These are written into the report as `dimension_labels` and used by the
    frontend to relabel score bars and the strongest/weakest summary cards.
    """
    r = role.lower()

    _pm_keys = ["product manager", " pm ", "product lead", "product owner",
                "product intern", "product associate", "associate product",
                "apm", "growth pm", "head of product", "vp of product", "director of product"]
    if any(k in f" {r} " for k in _pm_keys):
        return {
            "technical_depth":       "Product Thinking",
            "communication_quality": "Communication",
            "epistemic_calibration": "Analytical Rigor",
            "groundedness":          "Metrics Depth",
        }

    _strategy_keys = ["strategy", "strategist", "consultant", "business analyst",
                      "strategy intern", "strategy associate", "strategy analyst"]
    if any(k in r for k in _strategy_keys):
        return {
            "technical_depth":       "Analytical Thinking",
            "communication_quality": "Structured Communication",
            "epistemic_calibration": "Intellectual Honesty",
            "groundedness":          "Quantitative Rigor",
        }

    _ds_keys = ["data scientist", "data analyst", "ml engineer", "machine learning engineer",
                "analytics engineer"]
    if any(k in r for k in _ds_keys):
        return {
            "technical_depth":       "ML / Data Depth",
            "communication_quality": "Communication",
            "epistemic_calibration": "Epistemic Calibration",
            "groundedness":          "Specificity",
        }

    # Engineering / backend default — keep the original labels
    return {
        "technical_depth":       "Technical Depth",
        "communication_quality": "Communication",
        "epistemic_calibration": "Epistemic Calibration",
        "groundedness":          "Groundedness",
    }


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

    # Domain-first tiebreaker: communication_quality should not overshadow genuine domain performance.
    # If communication_quality is the top dimension but a domain dimension is within 0.3 of it,
    # prefer the domain dimension as "strongest" so the report highlights domain competency.
    _DOMAIN_DIMS = {"technical_depth", "groundedness", "epistemic_calibration"}
    if strongest == "communication_quality":
        cq_score = d["communication_quality"]
        domain_candidates = [(k, d[k]) for k in _DOMAIN_DIMS if k in d]
        if domain_candidates:
            best_domain_key, best_domain_score = max(domain_candidates, key=lambda x: x[1])
            # If the best domain dimension is within 0.3 of communication, prefer it
            if cq_score - best_domain_score <= 0.3:
                strongest = best_domain_key

    # Ensure strongest never equals weakest
    if strongest == weakest:
        sorted_keys = sorted(d.keys(), key=lambda k: d[k])
        strongest = sorted_keys[-1]
        weakest = sorted_keys[0]
        if strongest == weakest:
            return "", ""

    return strongest, weakest


def _compute_overall_score(
    turns: list[TurnRecord],
    warm_up_weight: float,
    trajectory: "ScoreTrajectory",
) -> float:
    """
    Deterministic overall score on a 0–10 scale.
    Formula: normalise the weighted average of the four dimensions from [1,5] → [0,10],
    then apply a small trajectory adjustment (±0.3) to reflect interview trend.
    Clamped to [1.0, 10.0] and rounded to one decimal place.
    """
    if not turns:
        return 5.0
    agg = _compute_scores(turns, warm_up_weight)
    d = agg.model_dump()
    avg_dim = sum(d.values()) / len(d)          # 1.0 – 5.0 range
    score = ((avg_dim - 1.0) / 4.0) * 10.0     # → 0.0 – 10.0

    # Reward a clearly improving trajectory; penalise a declining one
    bump = {
        "improving":        +0.3,
        "declining":        -0.3,
        "stable":            0.0,
        "insufficient_data": 0.0,
    }.get(getattr(trajectory, "value", str(trajectory)), 0.0)
    score += bump

    return round(max(1.0, min(10.0, score)), 1)


def _weakness_severity(scores: AggregateScores, weakest_key: str) -> str:
    """
    Returns "none", "minor", or "significant".
    "minor"  → weakest score ≥ 3.5 AND gap between strongest and weakest ≤ 0.8.
               Coach should soften language: "slight improvement opportunity", "not much", etc.
    "significant" → clear gap worth calling out directly.
    "none"   → all dimensions are close (extremes returned empty strings).
    """
    if not weakest_key:
        return "none"
    d = scores.model_dump()
    weakest_score = d.get(weakest_key, 0.0)
    max_score = max(d.values()) if d else 0.0
    gap = max_score - weakest_score
    if weakest_score >= 3.5 and gap <= 0.8:
        return "minor"
    return "significant"


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
    strongest_key, weakest_key = _extremes(agg)
    dim_labels = _role_dimension_labels(ctx.role)
    strongest = dim_labels.get(strongest_key, strongest_key) if strongest_key else ""
    weakest   = dim_labels.get(weakest_key,   weakest_key)   if weakest_key   else ""
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

    # Role-aware language for fallback strings
    role_lower = ctx.role.lower()
    if any(x in role_lower for x in ["product", "pm", "product lead", "product owner"]):
        depth_label = "product thinking and prioritization"
        grounding_label = "grounding product decisions in specific metrics and customer examples"
        practice = [
            f"Review your answers on {ctx.focus_area} and identify which prioritization decisions lacked concrete metrics or customer evidence.",
            "For each product decision you describe, prepare: the customer problem, the metric you optimized for, and one specific tradeoff you made.",
            f"Practice structuring a product strategy response on {ctx.focus_area}: problem definition → user segment → success metric → prioritized bets.",
        ]
    elif any(x in role_lower for x in ["strategy", "strategist", "consultant", "analyst", "associate"]):
        depth_label = "structured thinking and business reasoning"
        grounding_label = "grounding estimates and frameworks in specific numbers and named examples"
        practice = [
            f"Review your answers on {ctx.focus_area} and identify where your reasoning lacked explicit assumptions or quantified estimates.",
            "For each framework you mention, practice applying it to a real case with specific numbers rather than describing it in the abstract.",
            f"Practice structuring an estimation answer on a {ctx.focus_area} topic: state assumptions → build the estimate step by step → sense-check against known benchmarks.",
        ]
    else:
        depth_label = "technical depth and architectural reasoning"
        grounding_label = "grounding design choices in specific technologies and operational constraints"
        practice = [
            f"Review your answers on {ctx.focus_area} and identify where to add specific technology names, metrics, or implementation mechanics.",
            "Practice explaining one system design decision verbally in 2 minutes: state the constraint, the options you considered, and the tradeoff you made.",
            f"For each system you reference in {ctx.focus_area}, prepare: what it does, one key design decision, and one failure mode you'd need to handle.",
        ]

    overall_score = _compute_overall_score(
        substantive_turns, ctx.warm_up_score_weight, state.derived.score_trajectory
    )
    return CoachReport(
        session_id=ctx.session_id, role=ctx.role, focus_area=ctx.focus_area,
        total_turns=len(substantive_turns),
        interview_duration_approx=f"~{len(substantive_turns) * 2} minutes",
        overall_score=overall_score,
        overall_summary=(
            f"Interview completed with {len(substantive_turns)} turns on {ctx.focus_area}. "
            f"Strongest area: {strongest if strongest else 'balanced across dimensions'}. "
            f"Primary growth area: {weakest if weakest else 'consistent across dimensions'}."
        ),
        dimension_labels=dim_labels,
        score_summary=ScoreSummary(
            scores=agg, trajectory=state.derived.score_trajectory,
            strongest_dimension=strongest, weakest_dimension=weakest,
        ),
        strengths=[make_fp(
            f"Strongest performance in {strongest if strongest else depth_label}.", best,
            f"Continue building on {strongest if strongest else depth_label} with increasingly complex scenarios.",
        )],
        improvement_areas=[make_fp(
            f"Growth opportunity in {weakest if weakest else grounding_label}.", weak,
            f"Focus practice on {weakest if weakest else grounding_label} using specific examples from your experience.",
        )],
        communication_feedback=make_fp(
            "Communication quality assessed from transcript.", best,
            "Review your transcript and identify where adding structure (problem → approach → outcome) would improve clarity.",
        ),
        technical_feedback=make_fp(
            f"{depth_label.capitalize()} assessed from evaluator scores.", best,
            f"Practice grounding your answers in {grounding_label}.",
        ),
        practice_recommendations=practice,
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
