import logging
from typing import Optional

from state.models import InterviewState, ImmutableContext, DerivedSignals, AgentMailboxes
from orchestrator.graph import build_graph, make_initial_graph_state

logger = logging.getLogger(__name__)

_THREAD = lambda sid: {"configurable": {"thread_id": sid}}


class InterviewSession:
    _graph = None

    def __init__(self, session_id: str, initial_gs: dict):
        self._sid = session_id
        self._cfg = _THREAD(session_id)
        g = InterviewSession._get_graph()
        for _ in g.stream(initial_gs, config=self._cfg):
            pass

    @classmethod
    def _get_graph(cls):
        if cls._graph is None:
            cls._graph = build_graph()
        return cls._graph

    @classmethod
    def start(cls, context: ImmutableContext) -> "InterviewSession":
        state = InterviewState(context=context, derived=DerivedSignals(), mailboxes=AgentMailboxes())
        gs = make_initial_graph_state(state)
        logger.info(f"[Session] Starting {context.session_id}")
        return cls(context.session_id, gs)

    def _raw(self) -> dict:
        snap = InterviewSession._get_graph().get_state(self._cfg)
        if snap and snap.values:
            return snap.values.get("interview_state", {})
        return {}

    def current_question(self) -> str:
        return self._raw().get("current_question", "")

    def current_topic(self) -> str:
        return self._raw().get("current_topic", "")

    def current_phase(self) -> str:
        raw = self._raw().get("current_phase", "opening")
        if hasattr(raw, "value"):
            return raw.value
        s = str(raw)
        return s.split(".")[-1] if "." in s else s

    def turn_count(self) -> int:
        return len(self._raw().get("turns", []))

    def is_complete(self) -> bool:
        return bool(self._raw().get("is_complete", False))

    def submit_answer(self, answer: str) -> Optional[str]:
        if self.is_complete():
            return None
        g = InterviewSession._get_graph()
        g.update_state(self._cfg, {"human_input": answer})
        for _ in g.stream(None, config=self._cfg):
            pass
        return None if self.is_complete() else self.current_question()

    def get_report(self) -> Optional[dict]:
        return self._raw().get("_coach_report")

    def get_turn_log(self) -> list:
        return self._raw().get("turns", [])
