"""
Deterministic Signal Extractor — replaces the LLM-based Evaluator Agent.

This module is NOT an agent. It is a pure-Python function that extracts
heuristic signals from a candidate's answer in real time. These signals
drive the Strategy Agent's turn-by-turn planning.

Final evaluation authority belongs ONLY to the Coach Agent.
Scores produced here are heuristic baselines (3 ± 1) used for real-time
planning — they are NOT used in the final report.
"""
import logging
import re

from state.models import (
    InterviewState, EvaluatorOutput, EvaluatorScores,
    EvaluatorFlags, CrossTurnAnalysis,
)
from state.defaults import fallback_evaluator_output
from state.enums import EvaluationConfidence

logger = logging.getLogger(__name__)

# Minimum word count for a substantive answer
_MIN_WORDS = 25

# Phrases that indicate explicit uncertainty acknowledgement (positive epistemic signal)
_UNCERTAINTY_PHRASES = [
    "i'm not sure", "i am not sure", "i don't know", "i do not know",
    "i'm uncertain", "i am uncertain", "not certain", "not entirely sure",
    "i'd need to look into", "i would need to look into",
    "i'm not confident", "i'm less familiar", "i haven't worked with",
    "to be honest", "i'm guessing", "i'm not entirely sure",
    "i believe but i'm not certain", "good question and i'm not sure",
]

# Phrases that indicate vagueness / hedging without substance
_VAGUE_PHRASES = [
    "it depends", "kind of", "sort of", "generally speaking",
    "usually", "typically", "in most cases", "more or less",
    "pretty much", "i feel like", "something like",
    "at a high level", "you know", "basically",
    "stuff like that", "things like that", "and so on",
]

# Jargon words used without explanation (bluffing signal when combined with short answer)
_JARGON_PATTERN = re.compile(
    r'\b(?:infrastructure|architecture|scalability|microservices|distributed|'
    r'framework|pipeline|throughput|latency|algorithm|paradigm|ecosystem|'
    r'leverage|utilize|synergy|holistic|seamless|robust|enterprise|'
    r'stakeholder|alignment|visibility|bandwidth|actionable|deep.?dive)\b',
    re.IGNORECASE,
)

# Phrases that signal a feedback/end-of-interview request
_FEEDBACK_PATTERNS = [
    "can i get feedback", "can you give me feedback", "could i get feedback",
    "i'd like feedback", "i would like feedback", "give me feedback",
    "any feedback", "what feedback do you have",
    "how did i do", "how am i doing", "how did i perform",
    "can i get a review", "can i get a report", "can you give me a report",
    "can i see my report", "generate the report", "generate a report",
    "what are my results", "can we wrap up", "can we end the interview",
    "i want to end", "let's end", "let's wrap up",
]

# Phrases that signal the candidate is asking the interviewer a question
_CANDIDATE_QUESTION_PATTERNS = [
    "what does success look like", "what would my day look like",
    "what does a typical day", "what are the team challenges",
    "what is the culture like", "what's the culture like",
    "how does the team work", "what are the challenges on the team",
    "what do you enjoy about", "what's it like to work",
    "what is it like to work", "how do you see the role",
    "what would you say the role", "can you tell me about the team",
    "what is the role like", "what does the role involve",
    "how would you describe the role", "what are you looking for in a candidate",
    "what makes a great", "what does good look like in this role",
    "what are the growth opportunities", "how long have you been",
    "what brought you to", "why did you join", "how big is the team",
    "who would i be working with", "what tools do you use",
    "what's the tech stack", "what is the tech stack",
    "what does the interview process look like", "what are the next steps",
]


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers (kept for backwards-compat with any caller that imported them)
# ─────────────────────────────────────────────────────────────────────────────

def is_feedback_request(text: str) -> bool:
    """Return True if the candidate is asking for feedback or wrapping up."""
    t = text.strip().lower()
    return any(p in t for p in _FEEDBACK_PATTERNS)


def is_candidate_question(text: str) -> bool:
    """Return True if the candidate asked the interviewer a direct question."""
    stripped = text.strip()
    t = stripped.lower()
    if not stripped.endswith("?"):
        return False
    if len(stripped.split()) > 60:
        return False
    return any(p in t for p in _CANDIDATE_QUESTION_PATTERNS)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def extract_signals(state: InterviewState) -> tuple[EvaluatorOutput, bool]:
    """
    Extract heuristic signals from the current answer — no LLM call.

    Returns (EvaluatorOutput, is_valid).  Scores are heuristic baselines
    (3 ± 1) and are used ONLY for real-time Strategy planning.
    The Coach Agent generates the authoritative per-dimension scores at
    report time from the full interview transcript.
    """
    turn_index = len(state.turns)
    is_warm_up = (turn_index == 0)
    answer = state.current_answer or ""

    # ── Special input: feedback request ───────────────────────────────────────
    if is_feedback_request(answer):
        logger.info(f"[Signals] Turn {turn_index} — feedback request detected")
        neutral = fallback_evaluator_output(turn_index, is_warm_up)
        neutral.follow_up_signals = ["CANDIDATE_FEEDBACK_REQUEST"]
        neutral.reasoning = (
            "Candidate explicitly requested feedback/report. "
            "No substantive answer to evaluate."
        )
        return neutral, True

    # ── Special input: candidate asked interviewer a question ─────────────────
    if is_candidate_question(answer):
        logger.info(f"[Signals] Turn {turn_index} — candidate question detected")
        neutral = fallback_evaluator_output(turn_index, is_warm_up)
        neutral.follow_up_signals = ["CANDIDATE_QUESTION"]
        neutral.reasoning = (
            "Candidate asked the interviewer a question rather than answering. "
            "No substantive answer to evaluate."
        )
        return neutral, True

    # ── Heuristic flag extraction ─────────────────────────────────────────────
    flags = _extract_flags(answer)

    # ── Heuristic score derivation (baseline 3, adjusted by flags) ───────────
    scores = _derive_scores(flags)

    # ── Lightweight cross-turn check ──────────────────────────────────────────
    cross_turn = _check_cross_turn(state, answer)

    output = EvaluatorOutput(
        turn_index=turn_index,
        scores=scores,
        flags=flags,
        cross_turn=cross_turn,
        follow_up_signals=[],
        reasoning=_build_reasoning(flags, scores),
        unsupported_claims_detail=[],
        evaluation_confidence=EvaluationConfidence.LOW,
        is_warm_up_turn=is_warm_up,
    )
    active = [k for k, v in flags.model_dump().items() if v]
    logger.info(
        f"[Signals] Turn {turn_index} | flags={active} | "
        f"scores=TD:{scores.technical_depth} CQ:{scores.communication_quality} "
        f"EC:{scores.epistemic_calibration} GR:{scores.groundedness}"
    )
    return output, True


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────

def _extract_flags(answer: str) -> EvaluatorFlags:
    """Extract heuristic boolean flags from the answer text."""
    words = answer.split()
    word_count = len(words)
    t = answer.lower()

    very_short = word_count < _MIN_WORDS

    # Vague: multiple hedging/filler phrases with low word count
    vague_hits = sum(1 for p in _VAGUE_PHRASES if p in t)
    vague_answer = vague_hits >= 3 or (vague_hits >= 2 and word_count < 60)

    # Honest uncertainty: explicit "I don't know" style acknowledgement
    honest_uncertainty = any(p in t for p in _UNCERTAINTY_PHRASES)

    # Jargon density
    jargon_count = len(_JARGON_PATTERN.findall(t))

    # Bluffing risk: short answer with heavy jargon and no admitted uncertainty
    bluffing_risk = very_short and jargon_count >= 2 and not honest_uncertainty

    # Shallow terminology: borderline-short answer dense with jargon
    shallow_terminology = (
        not very_short and word_count < 50 and jargon_count >= 3
    )

    return EvaluatorFlags(
        vague_answer=vague_answer,
        bluffing_risk=bluffing_risk,
        honest_uncertainty=honest_uncertainty,
        very_short_answer=very_short,
        shallow_terminology=shallow_terminology,
        # These three cannot be reliably detected without an LLM:
        unsupported_claim=False,
        off_topic=False,
        depth_ceiling=False,
    )


def _derive_scores(flags: EvaluatorFlags) -> EvaluatorScores:
    """
    Derive heuristic 1–5 scores from flags.

    Baseline is 3 (neutral). Each flag shifts one or more scores by ±1.
    Results are clamped to [1, 5].
    """
    td = 3  # technical_depth
    cq = 3  # communication_quality
    ec = 3  # epistemic_calibration
    gr = 3  # groundedness

    if flags.very_short_answer:
        td -= 1
        gr -= 1
        cq -= 1

    if flags.vague_answer:
        gr -= 1
        ec -= 1

    if flags.honest_uncertainty:
        # Explicit uncertainty is a positive epistemic signal
        ec += 1

    if flags.bluffing_risk:
        ec -= 1
        gr -= 1

    if flags.shallow_terminology:
        td -= 1

    return EvaluatorScores(
        technical_depth=max(1, min(5, td)),
        communication_quality=max(1, min(5, cq)),
        epistemic_calibration=max(1, min(5, ec)),
        groundedness=max(1, min(5, gr)),
    )


def _check_cross_turn(state: InterviewState, answer: str) -> CrossTurnAnalysis:
    """
    Lightweight cross-turn check: detect likely recycled examples via 4-gram overlap.
    Cannot detect semantic contradictions without an LLM.
    """
    if not state.turns:
        return CrossTurnAnalysis(consistent=True)

    words = answer.lower().split()
    if len(words) < 10:
        return CrossTurnAnalysis(consistent=True)

    current_4grams = {
        " ".join(words[i:i + 4]) for i in range(len(words) - 3)
    }

    for t in state.turns[-3:]:
        prior_words = (t.answer or "").lower().split()
        if len(prior_words) < 10:
            continue
        prior_4grams = {
            " ".join(prior_words[i:i + 4]) for i in range(len(prior_words) - 3)
        }
        if len(current_4grams & prior_4grams) >= 4:
            return CrossTurnAnalysis(consistent=True, recycled_example=True)

    return CrossTurnAnalysis(consistent=True)


def _build_reasoning(flags: EvaluatorFlags, scores: EvaluatorScores) -> str:
    """Build a brief human-readable summary of heuristic signal extraction."""
    active = [k for k, v in flags.model_dump().items() if v]
    if not active:
        return (
            f"[Heuristic] No significant flags detected. "
            f"Neutral baseline scores: TD={scores.technical_depth} "
            f"CQ={scores.communication_quality} EC={scores.epistemic_calibration} "
            f"GR={scores.groundedness}."
        )
    return (
        f"[Heuristic] Flags: {', '.join(active)}. "
        f"Adjusted scores: TD={scores.technical_depth} CQ={scores.communication_quality} "
        f"EC={scores.epistemic_calibration} GR={scores.groundedness}."
    )
