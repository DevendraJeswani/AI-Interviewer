"""
Evidence retrieval layer for the coach agent.

Curates the most important turn-level evidence so LLM calls receive
targeted, pre-analyzed evidence rather than a raw full-transcript dump.
This is a pure Python layer — no LLM calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EvidenceBundle:
    strongest_turns: list[dict] = field(default_factory=list)     # top N turns by combined score
    weakest_turns: list[dict] = field(default_factory=list)        # bottom N turns by combined score
    vague_pattern_turns: list[dict] = field(default_factory=list)  # shallow/vague turns
    recovery_moments: list[dict] = field(default_factory=list)     # weak→strong sequences
    contradictions: list[dict] = field(default_factory=list)       # same-topic swings
    flag_summary: dict = field(default_factory=dict)               # flag counts across turns
    trajectory_notes: str = ""                                     # plain-language score trend
    full_turns: list[dict] = field(default_factory=list)           # complete reference


# ─────────────────────────────────────────────────────────────────────────────
# Scoring helpers
# ─────────────────────────────────────────────────────────────────────────────

def _combined_score(turn: dict) -> float:
    """
    Weighted combination of all four scoring dimensions.
    Domain dimensions (TD, GR) weighted higher than communication,
    matching the domain-first tiebreaker in the main scoring logic.
    """
    s = turn.get("scores", {})
    td = s.get("technical_depth", 0)
    cq = s.get("communication_quality", 0)
    ec = s.get("epistemic_calibration", 0)
    gr = s.get("groundedness", 0)
    return td * 0.35 + gr * 0.35 + ec * 0.15 + cq * 0.15


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def retrieve_evidence(turns_data: list[dict], top_n: int = 3) -> EvidenceBundle:
    """
    Curate evidence from the serialized turns list.

    Args:
        turns_data: Output of _serialize_turns() from the coach agent.
        top_n:      Number of strongest/weakest turns to surface.

    Returns:
        EvidenceBundle with curated evidence ready for LLM injection.
    """
    if not turns_data:
        return EvidenceBundle(full_turns=turns_data)

    substantive = [t for t in turns_data if not t.get("is_warm_up")]
    if not substantive:
        return EvidenceBundle(full_turns=turns_data)

    # ── Strongest / weakest turns ─────────────────────────────────────────
    scored = sorted(substantive, key=_combined_score, reverse=True)
    strongest = scored[:top_n]
    weakest = scored[-top_n:][::-1]  # worst-first

    # ── Shallow / vague pattern turns ─────────────────────────────────────
    vague_turns = [
        t for t in substantive
        if (t.get("flags", {}).get("vague_answer")
            or t.get("flags", {}).get("shallow_terminology")
            or t.get("scores", {}).get("groundedness", 5) <= 2)
    ]

    # ── Recovery moments: weak turn followed by a materially stronger one ─
    recovery_moments = []
    for i in range(len(substantive) - 1):
        curr = _combined_score(substantive[i])
        nxt = _combined_score(substantive[i + 1])
        if curr < 2.5 and nxt >= curr + 0.5:
            recovery_moments.append({
                "from_turn": substantive[i]["turn_index"],
                "to_turn": substantive[i + 1]["turn_index"],
                "from_score": round(curr, 2),
                "to_score": round(nxt, 2),
                "topic": substantive[i + 1].get("topic", ""),
            })

    # ── Contradictions: same topic, large depth swing ────────────────────
    contradictions = _detect_contradictions(substantive)

    # ── Flag summary ──────────────────────────────────────────────────────
    flag_summary: dict[str, int] = {}
    for t in substantive:
        for flag, val in t.get("flags", {}).items():
            if val:
                flag_summary[flag] = flag_summary.get(flag, 0) + 1

    # ── Trajectory narrative ──────────────────────────────────────────────
    trajectory_notes = _build_trajectory_notes(substantive)

    return EvidenceBundle(
        strongest_turns=strongest,
        weakest_turns=weakest,
        vague_pattern_turns=vague_turns,
        recovery_moments=recovery_moments,
        contradictions=contradictions,
        flag_summary=flag_summary,
        trajectory_notes=trajectory_notes,
        full_turns=turns_data,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Evidence analysis helpers
# ─────────────────────────────────────────────────────────────────────────────

def _detect_contradictions(turns: list[dict]) -> list[dict]:
    """
    Find pairs of turns on the same topic where the candidate's technical depth
    swung by >= 2 points. A large swing often indicates bluffing or inconsistency.
    """
    by_topic: dict[str, list[dict]] = {}
    for t in turns:
        topic = t.get("topic", "unknown")
        by_topic.setdefault(topic, []).append(t)

    contradictions = []
    for topic, topic_turns in by_topic.items():
        if len(topic_turns) < 2:
            continue
        depths = [t.get("scores", {}).get("technical_depth", 3) for t in topic_turns]
        max_d, min_d = max(depths), min(depths)
        if max_d - min_d >= 2:
            best_turn = topic_turns[depths.index(max_d)]
            worst_turn = topic_turns[depths.index(min_d)]
            contradictions.append({
                "topic": topic,
                "strong_turn": best_turn["turn_index"],
                "weak_turn": worst_turn["turn_index"],
                "swing": max_d - min_d,
            })
    return contradictions


def _build_trajectory_notes(turns: list[dict]) -> str:
    """Describe the score trajectory in plain language for LLM injection."""
    if len(turns) < 2:
        return "Insufficient turns to determine trajectory."

    scores = [_combined_score(t) for t in turns]
    mid = len(scores) // 2
    first_half_avg = sum(scores[:mid]) / max(1, mid)
    second_half_avg = sum(scores[mid:]) / max(1, len(scores) - mid)
    delta = second_half_avg - first_half_avg

    if delta > 0.4:
        direction = "clearly improving"
    elif delta > 0.15:
        direction = "slightly improving"
    elif delta < -0.4:
        direction = "clearly declining"
    elif delta < -0.15:
        direction = "slightly declining"
    else:
        direction = "stable"

    peak_idx = scores.index(max(scores))
    low_idx = scores.index(min(scores))
    peak_turn = turns[peak_idx]["turn_index"]
    low_turn = turns[low_idx]["turn_index"]

    return (
        f"Trajectory is {direction} "
        f"(first-half avg={first_half_avg:.2f}, second-half avg={second_half_avg:.2f}). "
        f"Peak performance at turn {peak_turn}; lowest at turn {low_turn}."
    )


# ─────────────────────────────────────────────────────────────────────────────
# LLM injection formatter
# ─────────────────────────────────────────────────────────────────────────────

def build_evidence_context(bundle: EvidenceBundle) -> str:
    """
    Format the evidence bundle as a structured text block for injection into
    LLM prompts. This surfaces curated evidence so the model writes observations
    grounded in specific turns rather than summarising generically.
    """
    lines: list[str] = []

    # Trajectory
    if bundle.trajectory_notes:
        lines.append(f"TRAJECTORY ANALYSIS: {bundle.trajectory_notes}")

    # Strongest turns
    if bundle.strongest_turns:
        lines.append("\nSTRONGEST TURNS (highest combined evaluator scores):")
        for t in bundle.strongest_turns:
            s = t.get("scores", {})
            answer_preview = (t.get("answer") or "")[:200]
            lines.append(
                f"  Turn {t['turn_index']} [{t.get('topic', '?')}] "
                f"TD={s.get('technical_depth','?')} GR={s.get('groundedness','?')} "
                f"EC={s.get('epistemic_calibration','?')} CQ={s.get('communication_quality','?')}\n"
                f"    Q: {(t.get('question') or '')[:120]}\n"
                f"    A: {answer_preview}{'...' if len(t.get('answer','')) > 200 else ''}"
            )

    # Weakest turns
    if bundle.weakest_turns:
        lines.append("\nWEAKEST TURNS (lowest combined evaluator scores):")
        for t in bundle.weakest_turns:
            s = t.get("scores", {})
            flags = [k for k, v in t.get("flags", {}).items() if v]
            answer_preview = (t.get("answer") or "")[:200]
            lines.append(
                f"  Turn {t['turn_index']} [{t.get('topic', '?')}] "
                f"TD={s.get('technical_depth','?')} GR={s.get('groundedness','?')} "
                f"Flags: {', '.join(flags) or 'none'}\n"
                f"    Q: {(t.get('question') or '')[:120]}\n"
                f"    A: {answer_preview}{'...' if len(t.get('answer','')) > 200 else ''}"
            )

    # Vague/shallow pattern
    if bundle.vague_pattern_turns:
        lines.append(f"\nSHALLOW / VAGUE PATTERN ({len(bundle.vague_pattern_turns)} turns flagged):")
        for t in bundle.vague_pattern_turns:
            preview = (t.get("answer") or "")[:150]
            lines.append(
                f"  Turn {t['turn_index']} [{t.get('topic','?')}]: "
                f"\"{preview}{'...' if len(t.get('answer','')) > 150 else ''}\""
            )

    # Recovery moments
    if bundle.recovery_moments:
        lines.append("\nRECOVERY MOMENTS (candidate rebounded after a weak turn):")
        for r in bundle.recovery_moments:
            lines.append(
                f"  Turn {r['from_turn']} (score {r['from_score']}) "
                f"-> Turn {r['to_turn']} (score {r['to_score']}) on '{r['topic']}'"
            )

    # Contradictions
    if bundle.contradictions:
        lines.append("\nCROSS-TURN INCONSISTENCIES (same topic, large depth swing):")
        for c in bundle.contradictions:
            lines.append(
                f"  Topic '{c['topic']}': Turn {c['strong_turn']} was strong, "
                f"Turn {c['weak_turn']} was weak (depth swing={c['swing']} pts)"
            )

    # Flag summary
    if bundle.flag_summary:
        significant = {k: v for k, v in bundle.flag_summary.items() if v > 0}
        if significant:
            flag_str = ", ".join(f"{k}={v}" for k, v in sorted(significant.items()))
            lines.append(f"\nFLAG TOTALS ACROSS ALL TURNS: {flag_str}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Quality validation (pure Python — no LLM)
# ─────────────────────────────────────────────────────────────────────────────

_BANNED_PHRASES = [
    "structure your answers", "practice system design", "be more concise",
    "use the STAR method", "communicate more clearly", "think out loud",
    "dive deeper", "provide more detail", "more thorough", "your answers were",
    "demonstrated strong", "showed good", "overall performance",
    "practice out loud", "research more",
]


def validate_report_quality(parsed: dict) -> list[str]:
    """
    Pure Python quality check on a draft report dict.
    Returns a list of issue strings. Empty list means the draft is clean.

    Checks:
      1. Banned phrases in suggestions / recommendations
      2. Empty or placeholder evidence excerpts
      3. Too-short observations that are probably generic
      4. Duplicate practice recommendations
    """
    issues: list[str] = []

    all_fps = (
        parsed.get("strengths", [])
        + parsed.get("improvement_areas", [])
        + ([parsed["communication_feedback"]] if parsed.get("communication_feedback") else [])
        + ([parsed["technical_feedback"]] if parsed.get("technical_feedback") else [])
    )

    for fp in all_fps:
        if not isinstance(fp, dict):
            continue
        sug = (fp.get("suggestion") or "").lower()
        for phrase in _BANNED_PHRASES:
            if phrase in sug:
                issues.append(f"Banned phrase in suggestion: '{phrase}'")
                break

        obs = fp.get("observation") or ""
        if len(obs) < 30:
            issues.append(f"Observation too short (possibly generic): '{obs[:60]}'")

        for ev in fp.get("evidence", []):
            if not isinstance(ev, dict):
                continue
            excerpt = ev.get("excerpt") or ""
            if len(excerpt) < 15 or excerpt.startswith("["):
                issues.append(f"Weak evidence excerpt: '{excerpt[:60]}'")

    recs = parsed.get("practice_recommendations", [])
    for rec in recs:
        rec_lower = (rec or "").lower()
        for phrase in _BANNED_PHRASES:
            if phrase in rec_lower:
                issues.append(f"Banned phrase in recommendation: '{phrase}'")
                break

    # Check for duplicated recommendations (simple prefix check)
    seen_prefixes: set[str] = set()
    for rec in recs:
        prefix = (rec or "")[:40].lower().strip()
        if prefix in seen_prefixes:
            issues.append(f"Duplicate recommendation prefix: '{prefix}'")
        seen_prefixes.add(prefix)

    return issues
