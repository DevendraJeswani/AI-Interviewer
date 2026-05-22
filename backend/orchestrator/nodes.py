import logging
from datetime import datetime, timezone

from state.models import (
    InterviewState, TurnRecord, AgentMailboxes,
    EvaluatorToStrategy, StrategyToInterviewer, PromptVersions,
    EvaluatorOutput, StrategyDecision, safe_rehydrate
)
from state.enums import InterviewPhase, NextAction
from state.defaults import fallback_evaluator_output, fallback_strategy_decision
from orchestrator.signals import compute_derived_signals
from prompts.registry import snapshot_all_versions

logger = logging.getLogger(__name__)


def init_node(state: InterviewState) -> dict:
    logger.info(f"[Init] {state.context.session_id}")
    signals = compute_derived_signals(state.context, [])
    first_topic = state.context.topic_list[0] if state.context.topic_list else "general"
    return {"derived": signals, "current_topic": first_topic, "current_phase": InterviewPhase.OPENING}


def interviewer_node(state: InterviewState) -> dict:
    from agents.interviewer.agent import ask

    mailbox = state.mailboxes.strategy_to_interviewer
    turn_index = len(state.turns)

    # ask() handles opening, closing, and all follow-up turns internally
    if mailbox:
        logger.info(f"[Interviewer] Turn {turn_index} | {mailbox.next_action.value} | {mailbox.target_topic}")
    else:
        logger.info(f"[Interviewer] Turn {turn_index} | opening")

    question = ask(state)
    updated_mb = state.mailboxes.model_copy(update={"strategy_to_interviewer": None})

    if mailbox is None or turn_index == 0:
        return {"current_question": question, "current_topic": state.current_topic,
                "mailboxes": updated_mb, "current_phase": InterviewPhase.QUESTIONING}

    new_phase = _phase(mailbox.next_action, mailbox.interview_phase)
    return {"current_question": question, "current_topic": mailbox.target_topic,
            "mailboxes": updated_mb, "current_phase": new_phase}


def evaluator_node(state: InterviewState) -> dict:
    from agents.evaluator.agent import evaluate

    turn_index = len(state.turns)
    logger.info(f"[Evaluator] Turn {turn_index}")
    output, _ = evaluate(state)

    mb = state.mailboxes.model_copy(update={
        "evaluator_to_strategy": EvaluatorToStrategy(
            flags=output.flags, follow_up_signals=output.follow_up_signals,
            evaluation_confidence=output.evaluation_confidence,
            cross_turn=output.cross_turn, reasoning_summary=output.reasoning,
        )
    })
    return {"mailboxes": mb, "_staged_evaluator_output": output}


def derive_signals_node(state: InterviewState) -> dict:
    signals = compute_derived_signals(state.context, state.turns)
    return {"derived": signals}


def strategy_node(state: InterviewState) -> dict:
    from agents.strategy.agent import decide

    turn_count = len(state.turns)
    logger.info(f"[Strategy] Turn {turn_count}")
    decision, guardrail = decide(state)

    mb = state.mailboxes.model_copy(update={
        "evaluator_to_strategy": None,
        "strategy_to_interviewer": StrategyToInterviewer(
            next_action=decision.next_action, target_topic=decision.target_topic,
            follow_up_intent=decision.follow_up_intent, difficulty_adjustment=decision.difficulty_adjustment,
            interview_phase=decision.interview_phase, reasoning=decision.reasoning,
        ),
    })
    new_phase = _phase(decision.next_action, state.current_phase)
    # Do NOT update current_topic here — interviewer_node will do it via mailbox.target_topic.
    # Updating it here would cause append_turn_node to record the NEXT topic instead of the CURRENT one.
    return {"mailboxes": mb, "current_phase": new_phase, "_staged_strategy_decision": decision}


def append_turn_node(state: InterviewState) -> dict:
    turn_index = len(state.turns)

    raw_ev = getattr(state, "_staged_evaluator_output", None)
    raw_st = getattr(state, "_staged_strategy_decision", None)

    ev_out = safe_rehydrate(raw_ev, EvaluatorOutput) or fallback_evaluator_output(turn_index)
    st_dec = safe_rehydrate(raw_st, StrategyDecision) or fallback_strategy_decision(state.current_topic, state.current_phase)

    vs = snapshot_all_versions()
    record = TurnRecord(
        turn_index=turn_index, phase=state.current_phase, topic=state.current_topic,
        question=state.current_question, answer=state.current_answer,
        evaluator_output=ev_out, strategy_decision=st_dec,
        prompt_versions=PromptVersions(evaluator=vs["evaluator"], strategy=vs["strategy"], interviewer=vs["interviewer"]),
        timestamp=datetime.now(timezone.utc),
    )
    logger.info(f"[AppendTurn] Turn {turn_index} | {st_dec.next_action.value}")
    return {"turns": list(state.turns) + [record],
            "current_question": "", "current_answer": "",
            "_staged_evaluator_output": None, "_staged_strategy_decision": None}


def coach_node(state: InterviewState) -> dict:
    from agents.coach.agent import generate_report
    logger.info(f"[Coach] {len(state.turns)} turns")
    report = generate_report(state)
    return {"is_complete": True, "current_phase": InterviewPhase.REPORTING,
            "_coach_report": report.model_dump()}


def _phase(action: NextAction, current: InterviewPhase) -> InterviewPhase:
    if action == NextAction.WRAP_UP:
        return InterviewPhase.CLOSING
    if current == InterviewPhase.OPENING:
        return InterviewPhase.QUESTIONING
    return current
