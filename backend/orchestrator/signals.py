from state.models import ImmutableContext, TurnRecord, DerivedSignals, AggregateScores
from state.enums import TopicStatus, ScoreTrajectory, DifficultyLevel, DifficultyAdjustment, NextAction
from state.defaults import WARM_UP_SCORE_WEIGHT, NORMAL_SCORE_WEIGHT, apply_difficulty_adjustment


def compute_derived_signals(context: ImmutableContext, turns: list[TurnRecord]) -> DerivedSignals:
    topic_coverage = _topic_coverage(context.topic_list, turns)
    depth_ceilings = _depth_ceilings(turns)
    topics_remaining = [t for t in context.topic_list if topic_coverage.get(t) == TopicStatus.UNVISITED]
    addressed = sum(1 for t in context.topic_list if topic_coverage.get(t) in (TopicStatus.VISITED, TopicStatus.DEPTH_CEILING))
    coverage_pct = round((addressed / len(context.topic_list)) * 100, 1) if context.topic_list else 0.0

    return DerivedSignals(
        topic_coverage=topic_coverage,
        aggregate_scores=_aggregate_scores(turns, context.warm_up_score_weight),
        score_trajectory=_trajectory(turns),
        depth_ceilings=depth_ceilings,
        consecutive_actions_on_topic=_consecutive(turns),
        current_difficulty=_current_difficulty(context.difficulty_target, turns),
        topics_remaining=topics_remaining,
        turn_count=len(turns),
        coverage_breadth_pct=coverage_pct,
    )


def _topic_coverage(topic_list: list[str], turns: list[TurnRecord]) -> dict[str, TopicStatus]:
    seen: dict[str, bool] = {}
    for t in turns:
        ceiling = t.evaluator_output.flags.depth_ceiling
        seen[t.topic] = seen.get(t.topic, False) or ceiling
    result = {}
    for topic in topic_list:
        if topic not in seen:
            result[topic] = TopicStatus.UNVISITED
        elif seen[topic]:
            result[topic] = TopicStatus.DEPTH_CEILING
        else:
            result[topic] = TopicStatus.VISITED
    return result


def _depth_ceilings(turns: list[TurnRecord]) -> list[str]:
    return sorted({t.topic for t in turns if t.evaluator_output.flags.depth_ceiling})


def _aggregate_scores(turns: list[TurnRecord], warm_up_weight: float) -> AggregateScores:
    if not turns:
        return AggregateScores()
    sums = {"technical_depth": 0.0, "communication_quality": 0.0, "epistemic_calibration": 0.0, "groundedness": 0.0}
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


def _trajectory(turns: list[TurnRecord]) -> ScoreTrajectory:
    substantive = [t for t in turns if t.turn_index != 0]
    if len(substantive) < 3:
        return ScoreTrajectory.INSUFFICIENT_DATA
    recent = substantive[-2:]
    prior = substantive[-4:-2] if len(substantive) >= 4 else substantive[:-2]
    if not prior:
        return ScoreTrajectory.INSUFFICIENT_DATA
    r_avg = sum(t.evaluator_output.scores.technical_depth for t in recent) / len(recent)
    p_avg = sum(t.evaluator_output.scores.technical_depth for t in prior) / len(prior)
    delta = r_avg - p_avg
    if delta >= 0.5:
        return ScoreTrajectory.IMPROVING
    if delta <= -0.5:
        return ScoreTrajectory.DECLINING
    return ScoreTrajectory.STABLE


def _consecutive(turns: list[TurnRecord]) -> dict[str, int]:
    if not turns:
        return {}
    current = turns[-1].topic
    streak = 0
    for t in reversed(turns):
        if t.topic == current:
            streak += 1
        else:
            break
    result = {current: streak}
    for t in turns:
        if t.topic != current and t.topic not in result:
            result[t.topic] = 0
    return result


def _current_difficulty(target: DifficultyLevel, turns: list[TurnRecord]) -> DifficultyLevel:
    d = target
    for t in turns:
        d = apply_difficulty_adjustment(d, t.strategy_decision.difficulty_adjustment)
    return d
