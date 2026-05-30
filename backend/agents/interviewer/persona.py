"""
Interviewer Persona — tracks and exposes the interviewer's current conversational stance.

Pure-Python, no LLM calls. Updates each turn from:
  - The evaluator's output (how good was the answer?)
  - The strategy decision (what action are we taking next?)
  - The interview mode (normal vs. grill)
  - The current interview plan (for strategic context)

The resulting ConversationalState is injected into the interviewer's task directive
so it can calibrate tone, pressure, and acknowledgment style dynamically.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from state.models import ConversationalState, EvaluatorOutput, StrategyDecision

if TYPE_CHECKING:
    from state.models import InterviewPlan


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic conversational state update
# ─────────────────────────────────────────────────────────────────────────────

def update_conversational_state(
    current: ConversationalState,
    eval_output: EvaluatorOutput,
    strategy_decision: StrategyDecision,
    interview_mode: str = "normal",
    interview_plan: Optional["InterviewPlan"] = None,
) -> ConversationalState:
    """
    Pure-Python update of the interviewer's conversational stance.
    Called once per turn in append_turn_node, after the evaluator and strategy have run.
    """
    scores = eval_output.scores
    flags = eval_output.flags

    is_weak = (
        scores.technical_depth <= 2
        or scores.groundedness <= 2
        or flags.vague_answer
        or flags.very_short_answer
    )
    is_strong = (
        scores.technical_depth >= 4
        and scores.groundedness >= 4
        and not flags.bluffing_risk
        and not flags.shallow_terminology
    )

    # Consecutive counters
    cons_weak = (current.consecutive_weak_turns + 1) if is_weak else 0
    cons_strong = (current.consecutive_strong_turns + 1) if is_strong else 0

    # ── Tone ─────────────────────────────────────────────────────────────────
    if interview_mode == "grill":
        if cons_weak >= 2:
            tone = "skeptical"
        else:
            tone = "direct"
    else:
        if is_strong:
            tone = "warm"
        elif cons_weak >= 2:
            tone = "direct"
        else:
            tone = "neutral"

    # ── Pressure ─────────────────────────────────────────────────────────────
    pressure = current.pressure_level
    if interview_mode == "grill":
        if is_weak:
            pressure = round(min(1.0, pressure + 0.10), 2)
        elif is_strong:
            pressure = round(max(0.3, pressure - 0.05), 2)
    else:
        if cons_weak >= 2:
            pressure = round(min(0.5, pressure + 0.08), 2)
        elif is_strong:
            pressure = round(max(0.0, pressure - 0.05), 2)

    # ── Active strategy label ─────────────────────────────────────────────────
    action = strategy_decision.next_action.value
    strategy_map = {
        "probe": "deep_probe",
        "challenge": "challenge",
        "recover": "recover",
        "wrap_up": "close",
        "pivot": "pivot_explore",
        "follow_up": "follow_up",
    }
    active_strategy = strategy_map.get(action, "follow_plan")

    # ── Angles attempted (dedup ring-buffer of last 10) ───────────────────────
    angles = list(current.angles_attempted)
    angle_key = f"{strategy_decision.target_topic}:{action}"
    if angle_key not in angles:
        angles.append(angle_key)
    angles = angles[-10:]

    # ── Candidate confidence read (from epistemic calibration) ────────────────
    epi = scores.epistemic_calibration
    if flags.honest_uncertainty:
        confidence_read = "uncertain"
    elif epi >= 4:
        confidence_read = "confident"
    elif epi <= 2:
        confidence_read = "guessing"
    else:
        confidence_read = "unknown"

    return ConversationalState(
        tone=tone,
        pressure_level=pressure,
        active_strategy=active_strategy,
        angles_attempted=angles,
        consecutive_weak_turns=cons_weak,
        consecutive_strong_turns=cons_strong,
        candidate_confidence_read=confidence_read,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Persona context block — injected into the interviewer directive
# ─────────────────────────────────────────────────────────────────────────────

def build_persona_context_block(
    conv_state: ConversationalState,
    plan: Optional["InterviewPlan"] = None,
) -> str:
    """
    Compact context block appended to the interviewer's task directive.
    Tells the interviewer how to calibrate tone and pressure this turn.
    """
    if conv_state is None:
        return ""

    lines = ["[PERSONA STATE]"]
    lines.append(
        f"Tone: {conv_state.tone} | Pressure: {conv_state.pressure_level:.0%} | "
        f"Strategy: {conv_state.active_strategy}"
    )
    lines.append(f"Candidate confidence read: {conv_state.candidate_confidence_read}")

    if conv_state.consecutive_weak_turns >= 2:
        lines.append(
            f"⚠ {conv_state.consecutive_weak_turns} consecutive weak turns — "
            "keep pace moderate, don't overwhelm"
        )
    if conv_state.consecutive_strong_turns >= 2:
        lines.append(
            f"✓ {conv_state.consecutive_strong_turns} consecutive strong turns — "
            "push harder, they can handle depth"
        )

    if plan and plan.reflection_flags:
        lines.append(f"Strategic flags: {', '.join(plan.reflection_flags)}")

    if plan and plan.candidate_memory.bluffing_incidents >= 2:
        lines.append(
            f"⚠ Bluffing detected {plan.candidate_memory.bluffing_incidents}x — "
            "probe claims for evidence, don't accept high-level assertions"
        )

    return "\n".join(lines)
