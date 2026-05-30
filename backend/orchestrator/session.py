import logging
from typing import Optional

from state.models import InterviewState, ImmutableContext, DerivedSignals, AgentMailboxes
from orchestrator.graph import build_graph, make_initial_graph_state

logger = logging.getLogger(__name__)

_THREAD = lambda sid: {"configurable": {"thread_id": sid}}

# Minimum number of substantive evaluated turns needed before a report is eligible.
# Warm-up, closing, candidate questions, and feedback requests do NOT count.
EARLY_TERMINATION_THRESHOLDS: dict[str, int] = {
    "normal": 5,
    "grill": 7,
}


def _count_substantive_turns(raw_turns: list) -> int:
    """
    Count turns that represent real, evaluated interview responses.

    Excluded from the count:
    - The warm-up turn (turn_index == 0 / is_warm_up_turn == True)
    - The closing topic turn
    - Turns where the candidate asked the interviewer a question
    - Turns where the candidate requested feedback/report early

    Works with both serialised dicts (from LangGraph state) and TurnRecord objects.
    """
    count = 0
    for t in raw_turns:
        if isinstance(t, dict):
            topic = t.get("topic", "")
            ev = t.get("evaluator_output", {})
            is_warm_up = ev.get("is_warm_up_turn", False) if isinstance(ev, dict) else False
            signals = ev.get("follow_up_signals", []) if isinstance(ev, dict) else []
        else:
            topic = getattr(t, "topic", "")
            ev = getattr(t, "evaluator_output", None)
            is_warm_up = getattr(ev, "is_warm_up_turn", False) if ev else False
            signals = getattr(ev, "follow_up_signals", []) if ev else []

        if (
            not is_warm_up
            and topic != "closing"
            and "CANDIDATE_FEEDBACK_REQUEST" not in signals
            and "CANDIDATE_QUESTION" not in signals
        ):
            count += 1
    return count


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
    def start(
        cls,
        context: ImmutableContext,
        character_persona: dict | None = None,
    ) -> "InterviewSession":
        state = InterviewState(
            context=context,
            derived=DerivedSignals(),
            mailboxes=AgentMailboxes(),
            character_persona=character_persona,
        )
        gs = make_initial_graph_state(state)
        persona_note = f" | persona={character_persona.get('persona_name', '?')!r}" if character_persona else ""
        logger.info(f"[Session] Starting {context.session_id}{persona_note}")
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

    def end_early(self) -> dict:
        """
        Attempt to end the interview before the natural conclusion and generate a report.

        Returns a dict with:
          - eligible (bool): whether there is enough data for a meaningful report
          - substantive_turns (int): how many real Q&A turns were evaluated
          - threshold (int): minimum required for this mode
          - interview_mode (str): "normal" or "grill"
          - already_complete (bool): True if the interview was already finished
          - error (str | None): set if report generation itself failed
        """
        # Already done — nothing extra to do
        if self.is_complete():
            return {
                "eligible": True,
                "already_complete": True,
                "substantive_turns": 0,
                "threshold": 0,
                "interview_mode": "normal",
            }

        raw = self._raw()
        raw_turns = raw.get("turns", [])
        ctx = raw.get("context", {})
        interview_mode = ctx.get("interview_mode", "normal") if isinstance(ctx, dict) else "normal"

        substantive_count = _count_substantive_turns(raw_turns)
        threshold = EARLY_TERMINATION_THRESHOLDS.get(interview_mode, 5)

        if substantive_count < threshold:
            logger.info(
                f"[Session.end_early] {self._sid} | ineligible: {substantive_count}/{threshold} turns"
            )
            return {
                "eligible": False,
                "substantive_turns": substantive_count,
                "threshold": threshold,
                "interview_mode": interview_mode,
            }

        # Sufficient depth — generate report directly, bypassing the LangGraph pipeline
        from state.models import InterviewState
        from state.enums import InterviewPhase
        from agents.coach.agent import generate_report

        try:
            clean = {k: v for k, v in raw.items() if not k.startswith("_")}
            state = InterviewState.model_validate(clean)
            report = generate_report(state)
            report_dict = report.model_dump()
        except Exception as exc:
            logger.error(f"[Session.end_early] Report generation failed: {exc}", exc_info=True)
            return {
                "eligible": True,
                "already_complete": False,
                "substantive_turns": substantive_count,
                "threshold": threshold,
                "interview_mode": interview_mode,
                "error": str(exc),
            }

        # Persist report + completion flag into the LangGraph checkpoint so that
        # get_report() and is_complete() behave identically to a natural completion.
        updated_raw = dict(raw)
        updated_raw["is_complete"] = True
        updated_raw["current_phase"] = InterviewPhase.REPORTING.value
        updated_raw["_coach_report"] = report_dict

        g = InterviewSession._get_graph()
        g.update_state(self._cfg, {"interview_state": updated_raw})

        logger.info(
            f"[Session.end_early] {self._sid} | report generated | "
            f"{substantive_count}/{threshold} turns | mode={interview_mode}"
        )
        return {
            "eligible": True,
            "already_complete": False,
            "substantive_turns": substantive_count,
            "threshold": threshold,
            "interview_mode": interview_mode,
        }

    def get_report(self) -> Optional[dict]:
        return self._raw().get("_coach_report")

    def get_turn_log(self) -> list:
        return self._raw().get("turns", [])
