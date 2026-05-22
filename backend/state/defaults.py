from state.enums import (
    NextAction, FollowUpIntent, DifficultyAdjustment,
    DifficultyLevel, InterviewPhase, EvaluationConfidence,
)
from state.models import (
    EvaluatorScores, EvaluatorFlags, CrossTurnAnalysis,
    EvaluatorOutput, StrategyDecision,
)

WARM_UP_SCORE_WEIGHT = 0.3
NORMAL_SCORE_WEIGHT = 1.0
MAX_CONSECUTIVE_ACTIONS_ON_TOPIC = 3
MIN_ANSWER_WORD_COUNT = 25

DIFFICULTY_PROGRESSION: dict[str, DifficultyLevel] = {
    "junior_up": DifficultyLevel.MID,
    "mid_up": DifficultyLevel.SENIOR,
    "senior_up": DifficultyLevel.STAFF,
    "staff_up": DifficultyLevel.STAFF,
    "junior_down": DifficultyLevel.JUNIOR,
    "mid_down": DifficultyLevel.JUNIOR,
    "senior_down": DifficultyLevel.MID,
    "staff_down": DifficultyLevel.SENIOR,
}


def apply_difficulty_adjustment(
    current: DifficultyLevel,
    adjustment: DifficultyAdjustment,
) -> DifficultyLevel:
    if adjustment in (DifficultyAdjustment.HOLD, DifficultyAdjustment.NONE):
        return current
    direction = "up" if adjustment == DifficultyAdjustment.INCREASE else "down"
    key = f"{current.value}_{direction}"
    return DIFFICULTY_PROGRESSION.get(key, current)


def fallback_evaluator_output(turn_index: int, is_warm_up: bool = False) -> EvaluatorOutput:
    return EvaluatorOutput(
        turn_index=turn_index,
        scores=EvaluatorScores(
            technical_depth=3,
            communication_quality=3,
            epistemic_calibration=3,
            groundedness=3,
        ),
        flags=EvaluatorFlags(),
        cross_turn=CrossTurnAnalysis(consistent=True),
        follow_up_signals=[],
        reasoning="[FALLBACK] Evaluator output failed schema validation.",
        unsupported_claims_detail=[],
        evaluation_confidence=EvaluationConfidence.LOW,
        is_warm_up_turn=is_warm_up,
    )


def fallback_strategy_decision(
    current_topic: str,
    current_phase: InterviewPhase,
) -> StrategyDecision:
    return StrategyDecision(
        next_action=NextAction.FOLLOW_UP,
        target_topic=current_topic,
        difficulty_adjustment=DifficultyAdjustment.HOLD,
        follow_up_intent=FollowUpIntent.CLARIFY_VAGUENESS,
        interview_phase=current_phase,
        reasoning="[FALLBACK] Strategy output failed schema validation.",
    )
