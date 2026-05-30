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
    COACH_CONTEXT_SYSTEM_PROMPT,
    COACH_CRITIQUE_SYSTEM_PROMPT,
    build_analysis_user_prompt,
    build_report_user_prompt,
    build_context_user_prompt,
    build_critique_user_prompt,
    _fmt_turns_ref,
)
from agents.coach.context_engine import build_role_expectations, format_expectations_block
from agents.coach.evidence import (
    retrieve_evidence,
    build_evidence_context,
    validate_report_quality,
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


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(state: InterviewState) -> CoachReport:
    logger.info(f"[Coach] Generating report | {len(state.turns)} turns")

    # Exclude closing-phase turns — they are wrap-up, not evaluable content
    substantive_turns = [t for t in state.turns if t.phase != InterviewPhase.CLOSING]
    logger.info(f"[Coach] Filtered to {len(substantive_turns)} substantive turns")

    turns_data = _serialize_turns(substantive_turns)

    # ── Evidence retrieval (pure Python — always runs) ────────────────────
    bundle = retrieve_evidence(turns_data, top_n=3)
    evidence_ctx = build_evidence_context(bundle)
    logger.info(
        f"[Coach] Evidence: {len(bundle.strongest_turns)} strongest, "
        f"{len(bundle.weakest_turns)} weakest, "
        f"{len(bundle.vague_pattern_turns)} vague, "
        f"{len(bundle.recovery_moments)} recovery, "
        f"{len(bundle.contradictions)} contradictions"
    )

    # ── Pass 1: Analysis (with evidence context) ──────────────────────────
    analysis_str, analysis_dict = _run_analysis(
        state, substantive_turns, turns_data, evidence_ctx
    )

    # ── Pass 1.5: Context Intelligence (role-aware ideal-answer analysis) ─
    contextual_intel = _run_context_pass(state, turns_data, analysis_dict)

    # ── Pass 2: Report draft ──────────────────────────────────────────────
    draft = _run_report(
        state, substantive_turns, turns_data, analysis_str, analysis_dict, contextual_intel
    )

    return draft


# ─────────────────────────────────────────────────────────────────────────────
# LLM passes
# ─────────────────────────────────────────────────────────────────────────────

def _run_analysis(
    state: InterviewState,
    substantive_turns: list[TurnRecord],
    turns_data: list[dict],
    evidence_ctx: str,
) -> tuple[str, dict]:
    ctx = state.context
    user_prompt = build_analysis_user_prompt(
        role=ctx.role,
        focus_area=ctx.focus_area,
        difficulty_target=ctx.difficulty_target.value,
        turns_data=turns_data,
        warm_up_weight=ctx.warm_up_score_weight,
        evidence_context=evidence_ctx,
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


def _run_context_pass(
    state: InterviewState,
    turns_data: list[dict],
    analysis_dict: dict,
) -> dict:
    """
    Pass 1.5 — Context Intelligence Pass.

    Generates role-aware ideal-answer signals, concept gap analysis, and role-fit
    assessment for the key (weaker) turns in the interview.

    Graceful degradation: returns an empty dict if the pass fails at any step.
    The report is fully usable without these results — new fields just won't appear.
    """
    ctx = state.context
    try:
        expectations = build_role_expectations(
            role=ctx.role,
            focus_area=ctx.focus_area,
            difficulty=ctx.difficulty_target.value,
        )
        expectations_block = format_expectations_block(expectations)

        user_prompt = build_context_user_prompt(
            role=ctx.role,
            focus_area=ctx.focus_area,
            difficulty_target=ctx.difficulty_target.value,
            turns_data=turns_data,
            analysis_dict=analysis_dict,
            expectations_block=expectations_block,
            retrieved_context=state.retrieved_context,
        )

        raw = _call_llm(COACH_CONTEXT_SYSTEM_PROMPT, user_prompt, max_tokens=1500)
        if raw is None:
            logger.warning("[Coach/Context] LLM call returned None — skipping context pass")
            return {}

        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            logger.warning("[Coach/Context] JSON parse failed — skipping context pass")
            return {}

        logger.info(
            f"[Coach/Context] Context pass complete: "
            f"{len(parsed.get('turn_insights', []))} insights, "
            f"role_fit={parsed.get('role_fit_rating', '?')}"
        )
        return parsed

    except Exception as e:
        logger.warning(f"[Coach/Context] Context pass failed: {e}", exc_info=False)
        return {}


def _run_report(
    state: InterviewState,
    substantive_turns: list[TurnRecord],
    turns_data: list[dict],
    analysis_str: str,
    analysis_dict: dict,
    contextual_intel: dict | None = None,
) -> CoachReport:
    ctx = state.context

    # Pre-compute severity so the report prompt can calibrate language.
    # Prefer Coach analysis scores (authoritative) over heuristic scores.
    agg_preview = _compute_scores(substantive_turns, ctx.warm_up_score_weight, analysis_dict)
    _, weakest_key_preview = _extremes(agg_preview)
    severity = _weakness_severity(agg_preview, weakest_key_preview)
    dim_labels_preview = _role_dimension_labels(ctx.role)
    weakest_label_preview = (
        dim_labels_preview.get(weakest_key_preview, weakest_key_preview)
        if weakest_key_preview else ""
    )

    # Summarise context pass results for injection into Pass 2 prompt
    intel = contextual_intel or {}
    context_summary_lines = []
    role_fit_rating = intel.get("role_fit_rating", "")
    role_fit_assessment = intel.get("role_fit_assessment", "")
    key_missing = intel.get("key_missing_concepts", [])
    turn_insights = intel.get("turn_insights", [])
    if role_fit_rating or role_fit_assessment:
        context_summary_lines.append(f"Role fit: {role_fit_rating} — {role_fit_assessment}")
    if key_missing:
        context_summary_lines.append(f"Cross-turn concept gaps: {', '.join(key_missing)}")
    if turn_insights:
        insight_lines = []
        for ti in turn_insights[:3]:
            missing = ti.get("missing_concepts", [])
            sev = ti.get("gap_severity", "")
            if missing or sev not in ("none", ""):
                insight_lines.append(
                    f"  Turn {ti.get('turn_index', '?')} [{ti.get('topic', '?')}]: "
                    f"gap_severity={sev}, missing reasoning: {', '.join(missing[:2])}"
                )
        if insight_lines:
            context_summary_lines.append("Per-turn coaching focus:\n" + "\n".join(insight_lines))
    contextual_intel_summary = "\n".join(context_summary_lines)

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
        contextual_intel_summary=contextual_intel_summary,
    )
    raw = _call_llm(COACH_REPORT_SYSTEM_PROMPT, user_prompt)
    if raw is None:
        return _fallback_report(state, substantive_turns, analysis_dict)

    parsed = _extract_json(raw)
    if parsed is None:
        return _fallback_report(state, substantive_turns, analysis_dict)

    # ── Pass 3: Quality validation + targeted critique (only if needed) ───
    parsed = _maybe_repair(parsed, turns_data)

    # ── Inject deterministic fields + context intelligence ────────────────
    parsed = _inject_deterministic(parsed, state, substantive_turns, contextual_intel, analysis_dict)
    try:
        return CoachReport(**parsed)
    except Exception as e:
        logger.warning(f"[Coach] Schema validation failed: {e}")
        return _fallback_report(state, substantive_turns, analysis_dict)


def _maybe_repair(parsed: dict, turns_data: list[dict]) -> dict:
    """
    Run the quality validation check. If issues are found, fire one targeted
    repair LLM call to fix them. Bounded at 1 repair attempt — if the repair
    also fails, we keep the original draft (better than nothing).
    """
    issues = validate_report_quality(parsed)
    if not issues:
        logger.info("[Coach] Quality check: PASS — no repair needed")
        return parsed

    logger.warning(f"[Coach] Quality issues found ({len(issues)}): {issues[:3]}...")

    turns_ref = _fmt_turns_ref(turns_data)
    repair_prompt = build_critique_user_prompt(
        draft_json=json.dumps(parsed, indent=2),
        issues=issues,
        turns_ref=turns_ref,
    )
    raw = _call_llm(COACH_CRITIQUE_SYSTEM_PROMPT, repair_prompt)
    if raw is None:
        logger.warning("[Coach] Repair call failed — using original draft")
        return parsed

    repaired = _extract_json(raw)
    if repaired is None or not isinstance(repaired, dict):
        logger.warning("[Coach] Repair call returned non-JSON — using original draft")
        return parsed

    # Validate the repair improved things
    repair_issues = validate_report_quality(repaired)
    if len(repair_issues) < len(issues):
        logger.info(f"[Coach] Repair reduced issues {len(issues)} -> {len(repair_issues)}")
        return repaired
    else:
        logger.info("[Coach] Repair didn't improve quality — keeping original draft")
        return parsed


# ─────────────────────────────────────────────────────────────────────────────
# LLM call wrapper
# ─────────────────────────────────────────────────────────────────────────────

def _call_llm(system_instruction: str, user_prompt: str, max_tokens: int = 2048) -> Optional[str]:
    def _invoke():
        response = _get_client().models.generate_content(
            model=_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text if response.text else None
    return call_with_retry(_invoke, "Coach")


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic field injection — these are NEVER LLM-generated
# ─────────────────────────────────────────────────────────────────────────────

def _inject_deterministic(
    parsed: dict,
    state: InterviewState,
    substantive_turns: list[TurnRecord],
    contextual_intel: dict | None = None,
    analysis_dict: dict | None = None,
) -> dict:
    ctx = state.context
    parsed["session_id"] = ctx.session_id
    parsed["role"] = ctx.role
    parsed["focus_area"] = ctx.focus_area
    parsed["total_turns"] = len(substantive_turns)
    parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
    parsed["prompt_version_coach"] = get_active_version_string("coach")
    parsed["interview_duration_approx"] = f"~{len(substantive_turns) * 2} minutes"

    # Use Coach analysis scores as the authoritative source; fall back to heuristics
    agg = _compute_scores(substantive_turns, ctx.warm_up_score_weight, analysis_dict)
    strongest_key, weakest_key = _extremes(agg)

    dim_labels = _role_dimension_labels(ctx.role)
    parsed["dimension_labels"] = dim_labels

    strongest_label = dim_labels.get(strongest_key, strongest_key) if strongest_key else ""
    weakest_label   = dim_labels.get(weakest_key,   weakest_key)   if weakest_key   else ""

    if "score_summary" not in parsed or not isinstance(parsed.get("score_summary"), dict):
        parsed["score_summary"] = {}
    parsed["score_summary"]["scores"] = agg.model_dump()
    parsed["score_summary"]["trajectory"] = state.derived.score_trajectory.value
    parsed["score_summary"]["strongest_dimension"] = strongest_label
    parsed["score_summary"]["weakest_dimension"]   = weakest_label
    parsed["weakness_severity"] = _weakness_severity(agg, weakest_key)
    parsed["overall_score"] = _compute_overall_score(
        substantive_turns, ctx.warm_up_score_weight, state.derived.score_trajectory, analysis_dict
    )
    parsed["topic_coverage"] = _build_coverage(state, substantive_turns, analysis_dict)

    # ── Context Intelligence Layer (Pass 1.5 results) ─────────────────────
    # Injected deterministically — never LLM-generated numbers.
    intel = contextual_intel or {}
    try:
        from report.models import TurnInsight
        raw_insights = intel.get("turn_insights", [])
        # Validate and coerce each insight — skip any that are malformed
        validated_insights = []
        for raw in raw_insights:
            if not isinstance(raw, dict):
                continue
            # Only include insights where coaching adds value
            severity = raw.get("gap_severity", "none")
            if severity not in ("minor", "major"):
                continue
            try:
                validated_insights.append(TurnInsight(
                    turn_index=int(raw.get("turn_index", 0)),
                    topic=str(raw.get("topic", "")),
                    ideal_signals=[str(s) for s in raw.get("ideal_signals", [])[:4]],
                    missing_concepts=[str(s) for s in raw.get("missing_concepts", [])[:4]],
                    ideal_answer_outline=str(raw.get("ideal_answer_outline", ""))[:400],
                    gap_severity=severity,
                ).model_dump())
            except Exception:
                pass
        parsed["turn_insights"] = validated_insights
        parsed["key_missing_concepts"] = [
            str(c) for c in intel.get("key_missing_concepts", [])[:3]
        ]
        parsed["role_fit_assessment"] = str(intel.get("role_fit_assessment", ""))[:500]
        parsed["role_fit_rating"] = str(intel.get("role_fit_rating", ""))
    except Exception as e:
        logger.warning(f"[Coach] Context intel injection failed: {e}")
        parsed.setdefault("turn_insights", [])
        parsed.setdefault("key_missing_concepts", [])
        parsed.setdefault("role_fit_assessment", "")
        parsed.setdefault("role_fit_rating", "")

    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# Score computation (deterministic)
# ─────────────────────────────────────────────────────────────────────────────

def _scores_from_analysis(analysis_dict: dict) -> Optional[AggregateScores]:
    """
    Extract authoritative dimension scores from the Coach analysis JSON.

    The analysis pass generates its own avg_score per dimension from the full
    transcript — these are the authoritative scores used in the final report.
    Returns None if the analysis dict is missing or malformed.
    """
    if not analysis_dict:
        return None
    dim = analysis_dict.get("dimension_analysis", {})
    if not dim:
        return None
    try:
        td = float(dim.get("technical_depth", {}).get("avg_score", 0) or 0)
        cq = float(dim.get("communication", {}).get("avg_score", 0) or 0)
        ec = float(dim.get("epistemic_calib", {}).get("avg_score", 0) or 0)
        gr = float(dim.get("groundedness", {}).get("avg_score", 0) or 0)
        # Sanity-check: all values must be in the valid 1–5 range
        if not all(1.0 <= v <= 5.0 for v in [td, cq, ec, gr]):
            return None
        return AggregateScores(
            technical_depth=round(td, 2),
            communication_quality=round(cq, 2),
            epistemic_calibration=round(ec, 2),
            groundedness=round(gr, 2),
        )
    except (TypeError, ValueError, AttributeError):
        return None


def _compute_scores(
    turns: list[TurnRecord],
    warm_up_weight: float,
    analysis_dict: dict | None = None,
) -> AggregateScores:
    """
    Compute aggregate scores for the report.

    Priority order:
    1. Coach analysis scores (authoritative — from LLM analysis of the full transcript).
    2. Heuristic scores from TurnRecord.evaluator_output (fallback only).
    """
    # Prefer Coach analysis scores when available
    if analysis_dict:
        from_analysis = _scores_from_analysis(analysis_dict)
        if from_analysis is not None:
            logger.debug("[Coach] Using analysis-derived authoritative scores.")
            return from_analysis

    # Fallback: weighted average of heuristic signal extractor scores
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
    max_val, min_val = max(vals), min(vals)
    if max_val - min_val <= 0.3:
        return "", ""

    strongest = max(d, key=d.get)
    weakest   = min(d, key=d.get)

    # Domain-first tiebreaker
    _DOMAIN_DIMS = {"technical_depth", "groundedness", "epistemic_calibration"}
    if strongest == "communication_quality":
        cq_score = d["communication_quality"]
        domain_candidates = [(k, d[k]) for k in _DOMAIN_DIMS if k in d]
        if domain_candidates:
            best_domain_key, best_domain_score = max(domain_candidates, key=lambda x: x[1])
            if cq_score - best_domain_score <= 0.3:
                strongest = best_domain_key

    if strongest == weakest:
        sorted_keys = sorted(d.keys(), key=lambda k: d[k])
        strongest = sorted_keys[-1]
        weakest   = sorted_keys[0]
        if strongest == weakest:
            return "", ""

    return strongest, weakest


def _compute_overall_score(
    turns: list[TurnRecord],
    warm_up_weight: float,
    trajectory: "ScoreTrajectory",
    analysis_dict: dict | None = None,
) -> float:
    """Deterministic 0–10 score. Formula: normalise weighted avg from [1,5] → [0,10]."""
    if not turns:
        return 5.0
    agg = _compute_scores(turns, warm_up_weight, analysis_dict)
    d = agg.model_dump()
    avg_dim = sum(d.values()) / len(d)
    score = ((avg_dim - 1.0) / 4.0) * 10.0
    bump = {
        "improving":        +0.3,
        "declining":        -0.3,
        "stable":            0.0,
        "insufficient_data": 0.0,
    }.get(getattr(trajectory, "value", str(trajectory)), 0.0)
    score += bump
    return round(max(1.0, min(10.0, score)), 1)


def _weakness_severity(scores: AggregateScores, weakest_key: str) -> str:
    if not weakest_key:
        return "none"
    d = scores.model_dump()
    weakest_score = d.get(weakest_key, 0.0)
    max_score = max(d.values()) if d else 0.0
    gap = max_score - weakest_score
    if weakest_score >= 3.5 and gap <= 0.8:
        return "minor"
    return "significant"


def _build_coverage(
    state: InterviewState,
    substantive_turns: list[TurnRecord],
    analysis_dict: dict | None = None,
) -> list[dict]:
    # Build a topic → avg_depth lookup from the Coach analysis when available.
    # This gives us authoritative depth scores rather than heuristic scores.
    analysis_topic_depths: dict[str, float] = {}
    if analysis_dict:
        for tp in analysis_dict.get("topic_performance", []):
            t_name = tp.get("topic", "")
            t_depth = tp.get("avg_depth")
            if t_name and t_depth is not None:
                try:
                    analysis_topic_depths[t_name] = float(t_depth)
                except (TypeError, ValueError):
                    pass

    result = []
    for topic, status in state.derived.topic_coverage.items():
        if topic == "closing":
            continue
        topic_turns = [t for t in substantive_turns if t.topic == topic]

        # Prefer analysis-derived depth; fall back to heuristic scores
        if topic in analysis_topic_depths:
            peak = round(analysis_topic_depths[topic])
        else:
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


# ─────────────────────────────────────────────────────────────────────────────
# Fallback (schema generation failed after all passes)
# ─────────────────────────────────────────────────────────────────────────────

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
        )] if turn else [TurnEvidence(turn_index=0, excerpt="[Fallback]", relevance="[Fallback report]")]
        return FeedbackPoint(observation=obs, evidence=ev, suggestion=sug)

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
