import logging
from typing import Optional
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from state.models import InterviewState, AgentMailboxes, DerivedSignals
from state.enums import InterviewPhase
from orchestrator.nodes import (
    init_node, interviewer_node, evaluator_node,
    derive_signals_node, strategy_node, append_turn_node, coach_node,
)
from orchestrator.edges import (
    route_after_append,
    NODE_INIT, NODE_INTERVIEWER, NODE_EVALUATOR,
    NODE_DERIVE_SIGNALS, NODE_STRATEGY, NODE_APPEND_TURN, NODE_COACH,
)

logger = logging.getLogger(__name__)


class GraphState(TypedDict):
    interview_state: dict
    human_input: Optional[str]


def _load(gs: GraphState) -> InterviewState:
    raw = dict(gs["interview_state"])
    clean = {k: v for k, v in raw.items() if not k.startswith("_")}
    try:
        state = InterviewState.model_validate(clean)
    except Exception as e:
        logger.error(f"[_load] InterviewState validation failed: {e}. Keys: {list(clean.keys())}", exc_info=True)
        raise
    for k, v in raw.items():
        if k.startswith("_"):
            try:
                object.__setattr__(state, k, v)
            except Exception:
                pass
    return state


def _serialize(v):
    """Recursively serialize Pydantic models and containers to JSON-safe dicts.
    Uses mode='json' so enum instances are stored as strings, not Python objects —
    prevents LangGraph checkpoint 'unregistered type' warnings (future-breaking).
    """
    if hasattr(v, "model_dump"):
        return v.model_dump(mode='json')
    if isinstance(v, list):
        return [_serialize(item) for item in v]
    if isinstance(v, dict):
        return {ik: _serialize(iv) for ik, iv in v.items()}
    return v


def _wrap(node_fn):
    def wrapper(gs: GraphState) -> GraphState:
        state = _load(gs)
        try:
            updates = node_fn(state)
        except Exception as e:
            logger.error(f"[{node_fn.__name__}] Node execution failed: {e}", exc_info=True)
            raise
        raw = dict(gs["interview_state"])
        for k, v in updates.items():
            if k.startswith("_"):
                if v is None:
                    raw.pop(k, None)
                else:
                    raw[k] = _serialize(v)
            else:
                raw[k] = _serialize(v)
        return {"interview_state": raw, "human_input": gs.get("human_input")}
    wrapper.__name__ = node_fn.__name__
    return wrapper


def _human_input_node(gs: GraphState) -> GraphState:
    raw = dict(gs["interview_state"])
    raw["current_answer"] = gs.get("human_input") or ""
    return {"interview_state": raw, "human_input": None}


def _route(gs: GraphState) -> str:
    return route_after_append(_load(gs))


def build_graph(checkpointer=None):
    g = StateGraph(GraphState)
    g.add_node(NODE_INIT, _wrap(init_node))
    g.add_node(NODE_INTERVIEWER, _wrap(interviewer_node))
    g.add_node("human_input", _human_input_node)
    g.add_node(NODE_EVALUATOR, _wrap(evaluator_node))
    g.add_node(NODE_DERIVE_SIGNALS, _wrap(derive_signals_node))
    g.add_node(NODE_STRATEGY, _wrap(strategy_node))
    g.add_node(NODE_APPEND_TURN, _wrap(append_turn_node))
    g.add_node(NODE_COACH, _wrap(coach_node))

    g.set_entry_point(NODE_INIT)
    g.add_edge(NODE_INIT, NODE_INTERVIEWER)
    g.add_edge(NODE_INTERVIEWER, "human_input")
    g.add_edge("human_input", NODE_EVALUATOR)
    g.add_edge(NODE_EVALUATOR, NODE_DERIVE_SIGNALS)
    g.add_edge(NODE_DERIVE_SIGNALS, NODE_STRATEGY)
    g.add_edge(NODE_STRATEGY, NODE_APPEND_TURN)
    g.add_edge(NODE_COACH, END)
    g.add_conditional_edges(NODE_APPEND_TURN, _route, {NODE_INTERVIEWER: NODE_INTERVIEWER, NODE_COACH: NODE_COACH})

    return g.compile(checkpointer=checkpointer or MemorySaver(), interrupt_before=["human_input"])


def make_initial_graph_state(state: InterviewState) -> GraphState:
    return {"interview_state": state.model_dump(mode='json'), "human_input": None}
