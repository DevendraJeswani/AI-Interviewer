import logging
from state.models import InterviewState
from state.enums import InterviewPhase, NextAction

logger = logging.getLogger(__name__)

NODE_INIT = "init"
NODE_INTERVIEWER = "interviewer"
NODE_EVALUATOR = "evaluator"
NODE_DERIVE_SIGNALS = "derive_signals"
NODE_STRATEGY = "strategy"
NODE_APPEND_TURN = "append_turn"
NODE_COACH = "coach"
NODE_END = "__end__"


def route_after_append(state: InterviewState) -> str:
    if state.is_complete:
        return NODE_COACH
    if not state.turns:
        return NODE_INTERVIEWER
    last = state.turns[-1]
    
    # If the last turn was on the "closing" topic, we have already asked the closing words 
    # and the candidate has responded, so we transition to NODE_COACH to generate the report.
    if last.topic == "closing":
        return NODE_COACH
        
    # If the strategy decided WRAP_UP but we haven't asked the closing words yet,
    # route to NODE_INTERVIEWER so they can be spoken.
    if last.strategy_decision.next_action == NextAction.WRAP_UP:
        return NODE_INTERVIEWER
        
    if state.current_phase == InterviewPhase.CLOSING:
        return NODE_COACH
        
    return NODE_INTERVIEWER
