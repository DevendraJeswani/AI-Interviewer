import logging

from state.models import GuardrailResult

from state.models import StrategyDecision, DerivedSignals, EvaluatorOutput, TurnRecord, safe_rehydrate
from state.enums import NextAction, FollowUpIntent, DifficultyAdjustment, InterviewPhase, TopicStatus
from state.defaults import MAX_CONSECUTIVE_ACTIONS_ON_TOPIC, apply_difficulty_adjustment

logger = logging.getLogger(__name__)





def is_weak_candidate(turns: list[TurnRecord] | None, current_evaluator: EvaluatorOutput | None) -> bool:
    if not turns and not current_evaluator:
        return False
    evaluations = []
    if turns:
        for t in turns:
            hydrated_t = safe_rehydrate(t.evaluator_output, EvaluatorOutput)
            if hydrated_t:
                evaluations.append(hydrated_t)
    if current_evaluator:
        hydrated_c = safe_rehydrate(current_evaluator, EvaluatorOutput)
        if hydrated_c:
            evaluations.append(hydrated_c)
        
    substantive_evals = [e for e in evaluations if not e.is_warm_up_turn]
    if not substantive_evals:
        return False
        
    def _turn_is_weak(e: EvaluatorOutput) -> bool:
        return (
            e.scores.technical_depth <= 2
            or e.scores.groundedness <= 2
            or e.flags.vague_answer
            or e.flags.bluffing_risk
            or e.flags.shallow_terminology
            or e.flags.very_short_answer
            # honest_uncertainty is NOT a weakness signal — it is positive calibration
        )

    weak_turns_count = sum(1 for e in substantive_evals if _turn_is_weak(e))
    ratio_weak = weak_turns_count / len(substantive_evals)

    if len(substantive_evals) >= 2:
        last_two_weak = _turn_is_weak(substantive_evals[-1]) and _turn_is_weak(substantive_evals[-2])
        return ratio_weak >= 0.5 or last_two_weak
        
    return ratio_weak >= 0.5


def apply_all_guardrails(
    decision: StrategyDecision,
    derived: DerivedSignals,
    evaluator: EvaluatorOutput,
    target_turn_count: int,
    turns: list[TurnRecord] = None,
) -> GuardrailResult:
    overrides: list[str] = []
    d = decision

    is_weak = is_weak_candidate(turns, evaluator)
    effective_target = target_turn_count
    if is_weak:
        effective_target = max(3, target_turn_count - 2)
        logger.warning(f"[Guardrail] WEAK_CANDIDATE detected. Shortened target turns to {effective_target}.")

    # 1. Turn limit → force wrap_up
    if derived.turn_count >= effective_target:
        if d.next_action != NextAction.WRAP_UP:
            reason = "WEAK_CANDIDATE_LIMIT" if is_weak else "TURN_LIMIT"
            overrides.append(f"{reason}: {derived.turn_count}>={effective_target} → wrap_up")
            d = d.model_copy(update={
                "next_action": NextAction.WRAP_UP, "target_topic": "closing",
                "follow_up_intent": FollowUpIntent.NONE, "interview_phase": InterviewPhase.CLOSING,
                "difficulty_adjustment": DifficultyAdjustment.NONE,
            })
        _log(overrides)
        return GuardrailResult(d, overrides, bool(overrides))

    # 1.5 Weak candidate → block probe and challenge, force pivot or simpler follow up
    if is_weak and d.next_action in (NextAction.PROBE, NextAction.CHALLENGE):
        overrides.append("WEAK_CANDIDATE: probe/challenge blocked → follow_up simpler_reframe or pivot")
        remaining = [t for t in derived.topics_remaining if t != d.target_topic]
        if remaining:
            d = d.model_copy(update={
                "next_action": NextAction.PIVOT,
                "target_topic": remaining[0],
                "follow_up_intent": FollowUpIntent.NONE,
                "difficulty_adjustment": DifficultyAdjustment.DECREASE,
            })
        else:
            d = d.model_copy(update={
                "next_action": NextAction.FOLLOW_UP,
                "follow_up_intent": FollowUpIntent.SIMPLER_REFRAME,
                "difficulty_adjustment": DifficultyAdjustment.DECREASE,
            })

    # 2. Depth ceiling → force pivot (only blocks probe)
    if evaluator.flags.depth_ceiling and d.next_action == NextAction.PROBE:
        overrides.append("DEPTH_CEILING: probe blocked → pivot")
        d = d.model_copy(update={
            "next_action": NextAction.PIVOT,
            "target_topic": _pick_pivot(d.target_topic, derived),
            "follow_up_intent": FollowUpIntent.NONE,
            "difficulty_adjustment": DifficultyAdjustment.HOLD,
        })

    # 3. Consecutive cap → force pivot
    consecutive = derived.consecutive_actions_on_topic.get(d.target_topic, 0)
    if consecutive >= MAX_CONSECUTIVE_ACTIONS_ON_TOPIC and d.next_action not in (NextAction.PIVOT, NextAction.WRAP_UP):
        overrides.append(f"CONSECUTIVE_CAP: {consecutive} actions on '{d.target_topic}' → pivot")
        d = d.model_copy(update={
            "next_action": NextAction.PIVOT,
            "target_topic": _pick_pivot(d.target_topic, derived),
            "follow_up_intent": FollowUpIntent.NONE,
        })

    # 4. Honest uncertainty → block probe
    if evaluator.flags.honest_uncertainty and d.next_action == NextAction.PROBE:
        overrides.append("HONEST_UNCERTAINTY: probe blocked → follow_up simpler_reframe")
        d = d.model_copy(update={
            "next_action": NextAction.FOLLOW_UP,
            "follow_up_intent": FollowUpIntent.SIMPLER_REFRAME,
            "difficulty_adjustment": DifficultyAdjustment.DECREASE,
        })

    # 5. Intent integrity
    if d.next_action in (NextAction.PROBE, NextAction.FOLLOW_UP) and d.follow_up_intent == FollowUpIntent.NONE:
        overrides.append(f"INTENT_REQUIRED: {d.next_action.value} needs intent → pivot")
        d = d.model_copy(update={
            "next_action": NextAction.PIVOT,
            "target_topic": _pick_pivot(d.target_topic, derived),
            "follow_up_intent": FollowUpIntent.NONE,
        })

    if d.next_action in (NextAction.PIVOT, NextAction.RECOVER, NextAction.WRAP_UP) and d.follow_up_intent != FollowUpIntent.NONE:
        overrides.append(f"INTENT_CLEAR: {d.next_action.value} must have intent=none")
        d = d.model_copy(update={"follow_up_intent": FollowUpIntent.NONE})

    # 6. Normalize wrap_up target topic
    if d.next_action == NextAction.WRAP_UP and d.target_topic != "closing":
        overrides.append(f"WRAP_UP_TARGET: normalizing target_topic to 'closing'")
        d = d.model_copy(update={"target_topic": "closing", "interview_phase": InterviewPhase.CLOSING})

    _log(overrides)
    return GuardrailResult(d, overrides, bool(overrides))


def _pick_pivot(current_topic: str, derived: DerivedSignals) -> str:
    remaining = [t for t in derived.topics_remaining if t != current_topic]
    if remaining:
        return remaining[0]
    revisitable = [t for t, s in derived.topic_coverage.items() if s == TopicStatus.VISITED and t != current_topic]
    return revisitable[0] if revisitable else "closing"


def _log(overrides: list[str]) -> None:
    for msg in overrides:
        logger.warning(f"[Guardrail] {msg}")
