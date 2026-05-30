"""
Strategy Planner — the agentic planning layer for the strategy agent.

Two kinds of updates happen each turn:
  1. Deterministic Python update  (update_plan_from_turn) — no LLM, runs every turn.
  2. LLM reflection               (run_reflection_if_needed) — 1 call every 3 turns.

The plan is stored on InterviewState.interview_plan and survives across turns
via the LangGraph MemorySaver checkpoint. It gives the strategy agent a persistent
mental model of the candidate rather than reconstructing everything from raw history.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING, Optional

from google import genai
from google.genai import types

from state.models import (
    CandidateMemory, CompetencyNote, ConversationalState, InterviewPlan,
    ImmutableContext, EvaluatorOutput, StrategyDecision,
)

if TYPE_CHECKING:
    from state.models import InterviewState

logger = logging.getLogger(__name__)

_REFLECTION_EVERY_N_TURNS = 3
_MODEL = "gemini-flash-lite-latest"

# Lazy Gemini client — shared with other agents but owned by planner
_client = None


def _get_planner_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# Plan initialisation
# ─────────────────────────────────────────────────────────────────────────────

def initialize_plan(context: ImmutableContext) -> InterviewPlan:
    """Create the initial interview plan from the session context."""
    topics = list(context.topic_list)
    pressure = 0.5 if context.interview_mode == "grill" else 0.3
    return InterviewPlan(
        active_objectives=topics,
        completed_objectives=[],
        competency_notes=[],
        candidate_memory=CandidateMemory(),
        difficulty_trajectory="stable",
        target_pressure=pressure,
        current_pressure=pressure,
        turns_since_last_reflection=0,
        last_reflection_notes="",
        reflection_flags=[],
        plan_version=0,
        initialized=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic plan update — runs every turn, no LLM
# ─────────────────────────────────────────────────────────────────────────────

def update_plan_from_turn(
    plan: InterviewPlan,
    eval_output: EvaluatorOutput,
    topic: str,
    strategy_decision: StrategyDecision,
    interview_mode: str = "normal",
) -> InterviewPlan:
    """
    Pure-Python update of the interview plan after one evaluated turn.
    No LLM calls — deterministic rules only.
    """
    # Deep-copy to avoid mutating the original model
    plan_data = plan.model_dump()
    plan = InterviewPlan.model_validate(plan_data)

    scores = eval_output.scores
    flags = eval_output.flags

    # ── 1. Update or create competency note for this topic ───────────────────
    note: Optional[CompetencyNote] = next(
        (n for n in plan.competency_notes if n.area == topic), None
    )
    if note is None:
        note = CompetencyNote(area=topic)
        plan.competency_notes.append(note)

    note.turns_explored += 1
    alpha = 1.0 / note.turns_explored  # exponential-ish rolling average
    note.avg_technical_score = round(
        (1 - alpha) * note.avg_technical_score + alpha * scores.technical_depth, 2
    )
    note.avg_grounding_score = round(
        (1 - alpha) * note.avg_grounding_score + alpha * scores.groundedness, 2
    )

    if scores.technical_depth >= 4 and scores.groundedness >= 4:
        note.has_strong_evidence = True

    if flags.vague_answer and not note.recurring_weakness:
        note.recurring_weakness = "vague_answer"
    elif flags.bluffing_risk and not note.recurring_weakness:
        note.recurring_weakness = "bluffing_risk"
    elif flags.shallow_terminology and not note.recurring_weakness:
        note.recurring_weakness = "shallow_terminology"

    # Mark explored if ≥2 turns OR strategy decided to pivot away
    action_val = strategy_decision.next_action.value
    if note.turns_explored >= 2 or action_val == "pivot":
        note.is_sufficiently_explored = True
        if topic in plan.active_objectives and topic not in plan.completed_objectives:
            plan.active_objectives.remove(topic)
            plan.completed_objectives.append(topic)

    # ── 2. Update candidate memory ───────────────────────────────────────────
    if not eval_output.is_warm_up_turn:
        mem = plan.candidate_memory

        # Strong moment
        if scores.technical_depth >= 4 and scores.groundedness >= 4:
            excerpt = f"{topic}: strong ({scores.technical_depth}/5 tech, {scores.groundedness}/5 grnd)"
            if excerpt not in mem.strong_moments:
                mem.strong_moments = (mem.strong_moments + [excerpt])[-5:]  # keep last 5

        # Bluffing / uncertainty tracking
        if flags.bluffing_risk:
            mem.bluffing_incidents += 1
        if flags.honest_uncertainty:
            mem.honest_uncertainty_count += 1

        # Contradictions
        ct = eval_output.cross_turn
        if ct and not ct.consistent and ct.contradiction_description:
            desc = ct.contradiction_description[:120]
            if desc not in mem.contradictions:
                mem.contradictions = (mem.contradictions + [desc])[-3:]

        # Vague patterns
        if flags.vague_answer and "vague answers" not in mem.vague_patterns:
            mem.vague_patterns.append("vague answers")

        # Confidence trend (simplified: based on recent epistemic_calibration)
        epi = scores.epistemic_calibration
        if epi >= 4:
            mem.confidence_trend = "confident"
        elif epi <= 2:
            mem.confidence_trend = "guessing"
        else:
            if mem.confidence_trend == "unknown":
                mem.confidence_trend = "stable"

    # ── 3. Difficulty trajectory ─────────────────────────────────────────────
    td = scores.technical_depth
    if td >= 4:
        plan.difficulty_trajectory = "increasing"
    elif td <= 2:
        plan.difficulty_trajectory = "decreasing"
    else:
        plan.difficulty_trajectory = "stable"

    # ── 4. Pressure adjustment (grill mode raises pressure on weak answers) ──
    if interview_mode == "grill":
        if td <= 2 or flags.bluffing_risk:
            plan.current_pressure = round(min(1.0, plan.current_pressure + 0.12), 2)
        elif td >= 4:
            plan.current_pressure = round(max(0.3, plan.current_pressure - 0.05), 2)
    else:
        # Normal mode: gentle pressure curve
        if td <= 2:
            plan.current_pressure = round(min(0.6, plan.current_pressure + 0.08), 2)
        elif td >= 4:
            plan.current_pressure = round(max(0.0, plan.current_pressure - 0.05), 2)

    # ── 5. Advance turn counters ─────────────────────────────────────────────
    plan.turns_since_last_reflection += 1
    plan.plan_version += 1

    return plan


# ─────────────────────────────────────────────────────────────────────────────
# LLM reflection — runs every N turns
# ─────────────────────────────────────────────────────────────────────────────

def run_reflection_if_needed(
    plan: InterviewPlan,
    state: "InterviewState",
) -> InterviewPlan:
    """
    Optionally run a single LLM call to reflect on the interview so far.
    Only fires when turns_since_last_reflection >= _REFLECTION_EVERY_N_TURNS.
    Failure is non-fatal — returns the original plan unchanged.
    """
    if plan.turns_since_last_reflection < _REFLECTION_EVERY_N_TURNS:
        return plan

    logger.info(f"[Planner] Running reflection at plan v{plan.plan_version}")

    ctx = state.context
    prompt = _build_reflection_prompt(plan, ctx, state.turns)

    try:
        response = _get_planner_client().models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.25,
                max_output_tokens=512,
            ),
        )
        raw_text = response.text or ""
        parsed = _parse_reflection_json(raw_text)

        plan_data = plan.model_dump()
        plan_data["last_reflection_notes"] = parsed.get("reflection_notes", plan.last_reflection_notes)
        plan_data["reflection_flags"] = parsed.get("strategic_flags", plan.reflection_flags)
        plan_data["difficulty_trajectory"] = parsed.get("difficulty_trajectory", plan.difficulty_trajectory)
        plan_data["turns_since_last_reflection"] = 0

        plan = InterviewPlan.model_validate(plan_data)
        logger.info(f"[Planner] Reflection complete | flags={plan.reflection_flags}")
    except Exception as exc:
        logger.warning(f"[Planner] Reflection failed (non-fatal): {exc}")
        # Reset counter so we don't retry every turn after failure
        plan_data = plan.model_dump()
        plan_data["turns_since_last_reflection"] = 0
        plan = InterviewPlan.model_validate(plan_data)

    return plan


def _build_reflection_prompt(
    plan: InterviewPlan,
    ctx: ImmutableContext,
    turns: list,
) -> str:
    competency_lines = []
    for n in plan.competency_notes:
        status = "✓ done" if n.is_sufficiently_explored else "○ active"
        competency_lines.append(
            f"  {n.area} [{status}]: {n.turns_explored} turns, "
            f"tech_avg={n.avg_technical_score:.1f}, grnd_avg={n.avg_grounding_score:.1f}"
            + (f", weakness={n.recurring_weakness}" if n.recurring_weakness else "")
        )
    competency_str = "\n".join(competency_lines) or "  (none yet)"

    mem = plan.candidate_memory
    mem_lines = []
    if mem.strong_moments:
        mem_lines.append(f"Strong moments: {'; '.join(mem.strong_moments)}")
    if mem.vague_patterns:
        mem_lines.append(f"Vague patterns: {', '.join(mem.vague_patterns)}")
    if mem.bluffing_incidents:
        mem_lines.append(f"Bluffing incidents: {mem.bluffing_incidents}")
    if mem.contradictions:
        mem_lines.append(f"Contradictions: {'; '.join(mem.contradictions)}")
    mem_str = "\n  ".join(mem_lines) if mem_lines else "(no patterns yet)"

    remaining = ", ".join(plan.active_objectives) or "(none)"
    completed = ", ".join(plan.completed_objectives) or "(none)"
    mode = getattr(ctx, "interview_mode", "normal")

    return f"""\
You are reviewing the mid-interview status of a {ctx.role} mock interview (mode: {mode.upper()}).
Candidate background: {ctx.candidate_background}

COMPETENCY NOTES:
{competency_str}

CANDIDATE MEMORY:
  {mem_str}

OBJECTIVES:
  Completed: {completed}
  Still active: {remaining}

CURRENT PLAN STATE:
  Difficulty trajectory: {plan.difficulty_trajectory}
  Pressure level: {plan.current_pressure:.0%}
  Previous reflection: {plan.last_reflection_notes or 'none'}

REFLECTION TASK:
Review everything above. Identify:
1. What is the single most important strategic insight about this candidate right now?
2. What specific flags should guide the next 2-3 turns (e.g., "push harder on metrics", "candidate bluffs on systems topics", "explore leadership depth")?
3. Should difficulty go up, down, or stay stable?

Return ONLY this JSON (no markdown, no explanation):
{{
  "reflection_notes": "<one insight about the candidate, ≤2 sentences>",
  "strategic_flags": ["<flag 1>", "<flag 2>"],
  "difficulty_trajectory": "<stable|increasing|decreasing>"
}}
"""


def _parse_reflection_json(text: str) -> dict:
    """Extract JSON from LLM reflection response."""
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object in the response
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Plan context block — formatted for injection into strategy prompt
# ─────────────────────────────────────────────────────────────────────────────

def build_plan_context_block(plan: InterviewPlan) -> str:
    """Format the current plan as a concise context block for the strategy prompt."""
    if not plan or not plan.initialized:
        return ""

    lines = [
        f"══ INTERVIEW PLAN (v{plan.plan_version}) ════════════════════════════════════",
        f"Trajectory: {plan.difficulty_trajectory} | Pressure: {plan.current_pressure:.0%}",
    ]

    if plan.reflection_flags:
        lines.append(f"Strategic flags: {', '.join(plan.reflection_flags)}")
    if plan.last_reflection_notes:
        lines.append(f"Reflection: {plan.last_reflection_notes}")

    if plan.completed_objectives:
        lines.append(f"Objectives done:  {', '.join(plan.completed_objectives)}")
    if plan.active_objectives:
        lines.append(f"Objectives left:  {', '.join(plan.active_objectives)}")

    mem = plan.candidate_memory
    alerts = []
    if mem.bluffing_incidents >= 2:
        alerts.append(f"⚠ bluffing x{mem.bluffing_incidents}")
    if mem.contradictions:
        alerts.append("⚠ contradictions detected")
    if mem.vague_patterns:
        alerts.append("⚠ recurring vagueness")
    if mem.strong_moments:
        alerts.append(f"✓ {len(mem.strong_moments)} strong moment(s)")
    if alerts:
        lines.append("Candidate signals: " + " | ".join(alerts))

    note_lines = []
    for n in plan.competency_notes:
        status = "✓" if n.is_sufficiently_explored else "○"
        score_str = f"tech={n.avg_technical_score:.1f}, grnd={n.avg_grounding_score:.1f}"
        weakness = f" [{n.recurring_weakness}]" if n.recurring_weakness else ""
        note_lines.append(
            f"  {status} {n.area:<28} {n.turns_explored}t  {score_str}{weakness}"
        )
    if note_lines:
        lines.append("Competency notes:")
        lines.extend(note_lines)

    lines.append("")  # trailing newline separator
    return "\n".join(lines)
