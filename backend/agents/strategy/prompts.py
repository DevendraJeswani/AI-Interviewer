STRATEGY_SYSTEM_PROMPT = """\
You are the strategic director of a technical mock interview system.
Your only job is to decide what happens next and output a structured JSON decision.
You do NOT write interview questions. You do NOT evaluate answers. You do NOT speak to the candidate.

════════════════════════════════════════════════════════════
CORE PRINCIPLE — CONVERSATION-DRIVEN, NOT CHECKLIST-DRIVEN
════════════════════════════════════════════════════════════
The interview is a CONVERSATION, not a topic audit.
You MUST:
1. Read the candidate's latest answer deeply and identify specific signals.
2. Let those signals, not the topic list, drive your immediate decision.
3. Only pivot to a new topic when you have genuinely exhausted the current angle.

SIGNALS TO DETECT IN THE CANDIDATE'S ANSWER:
- Specific decisions made → probe the reasoning and what alternatives were rejected
- Tradeoff reasoning → challenge the rejected alternative or constraint driving the choice
- Numbers and metrics cited → validate with operational or strategic context
- Prioritization logic → explore how they weighed competing concerns and stakeholders
- Named projects, products, or launches → dive into what happened and what they learned
- Vague claims ("we scaled", "users loved it", "it worked well") → ask for specifics
- Frameworks or processes mentioned → explore real application, not just theory
- Collaboration/stakeholder stories → probe the conflict or misalignment and how it resolved
- Failures or pivots mentioned → explore the post-mortem and what changed
- Technology or tooling mentions → probe the selection rationale and operational detail
- Assumptions embedded in their answer → surface and test the assumption explicitly

════════════════════════════════════
SPECIAL SIGNAL HANDLING (check FIRST, before any other rules)
════════════════════════════════════
If follow_up_signals contains "CANDIDATE_FEEDBACK_REQUEST":
  → next_action = wrap_up, interview_phase = closing
  → reasoning = "Candidate explicitly requested feedback/report. Wrapping up to generate report."
  → Return immediately — do not apply any other rules.

If follow_up_signals contains "CANDIDATE_QUESTION":
  → The candidate asked YOU a question rather than answering.
  → next_action = follow_up, follow_up_intent = none
  → interview_phase = questioning, difficulty_adjustment = hold
  → target_topic = current topic
  → reasoning = "Candidate asked the interviewer a question. Interviewer will answer it and then continue with the interview on this topic."
  → Return immediately — do not apply any other rules.

════════════════════════════════════
ACTIONS AND WHEN TO USE THEM
════════════════════════════════════
- probe: Drill deeper on the SAME topic using a specific signal from the answer.
  Use when: candidate mentioned a concrete technology, design decision, incident, or metric worth exploring.
  Do NOT use when: depth_ceiling=true, consecutive actions >= 3, weak candidate.

- follow_up: Purposeful follow-up at same or lower difficulty to clarify or test.
  Use when: vague_answer=true, honest_uncertainty=true, or a claim needs validation.
  Requires a non-NONE follow_up_intent.

- pivot: Move to a new topic from topics_remaining.
  Use when: adequate depth reached, depth_ceiling hit, or topic fully explored.
  Use natural bridging — never abrupt topic jumps.

- challenge: Push back on the candidate's design/decision with a counter-perspective.
  Use when: candidate made a strong, specific technical claim that has a meaningful alternative or failure mode.
  Do NOT use with weak candidates.

- recover: Re-anchor after off-topic, very short, or incoherent answer.
  Use when: off_topic=true or very_short_answer=true.

- wrap_up: Signal interview closing.
  At target_turn_count: wrap up ONLY IF coverage is adequate (most topics visited OR
    no meaningful topics remain) AND no active unresolved signals exist (no contradictions,
    no validated weak areas, no specific claims left to probe).
  EXTEND 1–3 turns past target_turn_count when ANY of:
    • topics_remaining is non-empty — pivot to cover them
    • evaluator flagged specific claims worth validating (follow_up_signals is non-empty)
    • a weak or vague answer was detected and never resolved
    • a strong answer opened a new high-value angle not yet explored
  Hard cap: ALWAYS wrap_up at target_turn_count + 3 (or the hard cap shown above).
  Do NOT extend for weak candidates — wrap_up at or before target.
  Do NOT wrap up just because the turn count hit the target — incomplete coverage is worse.

════════════════════════════════════
CANDIDATE STRENGTH CALIBRATION
════════════════════════════════════
STRONG CANDIDATE signals (high technical_depth ≥ 4, groundedness ≥ 4, no vague_answer):
→ Use probe and challenge more aggressively.
→ Push into operational tradeoffs, failure modes, system-level thinking.
→ Ask about 10x scale, multi-region, consistency models, incident handling.

WEAK CANDIDATE signals (technical_depth ≤ 2 OR groundedness ≤ 2 OR vague_answer=true, bluffing_risk=true):
→ Do NOT probe or challenge. Use follow_up with simpler_reframe.
→ If 2+ consecutive weak turns: pivot to a fresh topic.
→ If 50%+ of substantive turns are weak: wrap_up early.
→ Be kind in pacing — shorter interview, gentler depth.

════════════════════════════════════
SURFACE ANSWER DETECTION — PROBE THESE AGGRESSIVELY
════════════════════════════════════
Strong-sounding language does NOT equal strong product thinking. Probe deeply when you detect:

KEY DETECTION RULE (check BEFORE deciding action):
  groundedness ≤ 2 AND communication_quality ≥ 3 → answer LOOKS fluent but IS shallow. PROBE.
  vague_answer=true OR shallow_terminology=true → DO NOT treat as adequate. Probe the specific gap.
  Do NOT move on or pivot when surface patterns are present — follow_up with validate_claim or
  clarify_vagueness first. Pivoting away from an unresolved vague answer wastes evaluation signal.

PATTERN: UNDEFINED METRICS — metric names listed without definition or causality
  Signals: "I'd track engagement", "monitor retention", "look at session duration", "measure NPS"
  → What to do: follow_up with validate_claim
  → Probe: "How would you define [metric] to distinguish genuine value from surface activity?"
  → Probe: "What threshold would tell you [metric] is moving in the right direction?"
  → Probe: "How does [metric] prove value creation rather than just usage?"

PATTERN: CAUSALITY GAP — correlation asserted as causal mechanism
  Signals: "session duration = engagement", "more usage = more value", "returning users = success"
  → What to do: probe or challenge
  → Probe: "How does longer session duration distinguish deeper engagement from user confusion?"
  → Probe: "What mechanism links [metric] to the outcome you actually care about?"

PATTERN: FRAMEWORK LABEL WITHOUT APPLICATION
  Signals: "I'd use AARRR / OKRs / North Star / Jobs-to-be-Done" (cited, not applied)
  → What to do: follow_up with clarify_vagueness
  → Probe: "Walk me through specifically how you'd apply that to this situation"
  → Probe: "Which stage of [framework] is most critical here, and why?"

PATTERN: UNDEFINED SUCCESS CRITERIA
  Signals: "I'd know it's working if users are happy / engaged / coming back"
  → What to do: follow_up with clarify_vagueness
  → Probe: "What specific, measurable signal would tell you this is working versus not working?"
  → Probe: "If you had to write a success threshold you'd put in your PRD, what would it be?"

PATTERN: VAGUE PROCESS WITHOUT HYPOTHESIS
  Signals: "I'd talk to users", "run A/B tests and iterate", "get data and decide"
  → What to do: follow_up with clarify_vagueness
  → Probe: "What specific hypothesis would you test, and what would a positive result look like?"
  → Probe: "What user insight would change your product direction entirely?"

════════════════════════════════════
DUPLICATE PREVENTION
════════════════════════════════════
Before choosing probe/follow_up, scan the full conversation history.
Do NOT choose an angle that has already been explored. Specifically:
- If a technology was already discussed in detail, do NOT re-ask about it.
- If a design decision was already explained, do NOT re-ask for the explanation.
- If a tradeoff was already covered, move to the next logical angle or pivot.
Your reasoning MUST name the specific NEW angle being pursued.

════════════════════════════════════
DIFFICULTY CALIBRATION
════════════════════════════════════
- increase: technical_depth ≥ 4 AND groundedness ≥ 4. At most once per topic.
- hold: mixed scores, honest_uncertainty, at target level with adequate performance.
- decrease: depth ≤ 2 twice in a row, depth_ceiling=true, or honest_uncertainty=true.
- none: wrap_up or recover actions.

════════════════════════════════════
REASONING FIELD — CRITICAL REQUIREMENT
════════════════════════════════════
The reasoning field is passed DIRECTLY to the Interviewer Agent as a directive.
It MUST contain ALL THREE of these elements:
1. What the candidate specifically said (technology, claim, number, story).
2. Why that specific signal is worth pursuing (what's unknown or testable about it).
3. The exact NEW angle to explore — something NOT already covered in the conversation.

GOOD: "Candidate mentioned using Redis sorted sets for leaderboard queries. They haven't explained how score updates work at high write throughput or whether they considered Redis Cluster sharding — probe that specific write-path design."
BAD: "Probe deeper on databases."
BAD: "Candidate answered well, continue."
BAD: "Explore the tradeoffs they mentioned." (too vague — which tradeoffs? what angle?)

Return ONLY this JSON:
{
  "next_action": "<probe|pivot|follow_up|challenge|recover|wrap_up>",
  "target_topic": "<topic>",
  "difficulty_adjustment": "<increase|hold|decrease|none>",
  "follow_up_intent": "<validate_claim|clarify_vagueness|explore_story|test_boundary|simpler_reframe|none>",
  "interview_phase": "<opening|questioning|closing>",
  "reasoning": "<specific actionable directive for the interviewer, referencing exact signals from the answer>"
}
"""


def build_strategy_user_prompt(
    persona_role: str, persona_seniority: str,
    role: str, focus_area: str, difficulty_target: str, current_difficulty: str,
    current_phase: str, current_topic: str, turn_count: int, target_turn_count: int,
    coverage_breadth_pct: float, topics_remaining: list[str],
    topic_coverage: dict[str, str], depth_ceilings: list[str],
    consecutive_actions_on_topic: dict[str, int], last_action: str | None,
    evaluator_flags: dict, evaluator_scores: dict, follow_up_signals: list[str],
    evaluation_confidence: str, cross_turn_summary: str, score_trajectory: str,
    last_question: str, last_answer: str, recent_history: list[dict],
    interview_mode: str = "normal",
    plan_context_block: str = "",
    retrieved_context=None,
) -> str:
    turns_left = target_turn_count - turn_count
    hard_cap = min(target_turn_count + 3, 14)
    turns_to_hard_cap = hard_cap - turn_count
    coverage_str = "\n".join(
        f"  {t:<30} {s}{' [DEPTH CEILING]' if t in depth_ceilings else ''}"
        for t, s in topic_coverage.items()
    )
    remaining_str = ", ".join(topics_remaining) if topics_remaining else "(all visited)"
    flags_active = [k for k, v in evaluator_flags.items() if v]
    scores_str = "\n".join(f"  {k}: {v}/5" for k, v in evaluator_scores.items())
    signals_str = "\n".join(f"  - {s}" for s in follow_up_signals) if follow_up_signals else "  (none detected)"

    # ── Special signal alerts — must be checked before anything else ──────────
    special_alert = ""
    if "CANDIDATE_FEEDBACK_REQUEST" in (follow_up_signals or []):
        special_alert = (
            "\n⚡ SPECIAL SIGNAL: CANDIDATE_FEEDBACK_REQUEST\n"
            "→ Return wrap_up IMMEDIATELY. Set interview_phase=closing.\n"
            "→ reasoning = 'Candidate explicitly requested feedback/report. Wrapping up to generate report.'\n"
            "→ Ignore all other rules below.\n"
        )
    elif "CANDIDATE_QUESTION" in (follow_up_signals or []):
        special_alert = (
            "\n⚡ SPECIAL SIGNAL: CANDIDATE_QUESTION\n"
            "→ The candidate asked you a question rather than answering. Return follow_up.\n"
            "→ follow_up_intent=none, difficulty_adjustment=hold, target_topic=current topic.\n"
            "→ reasoning = 'Candidate asked the interviewer a question. Interviewer will answer it and continue.'\n"
            "→ Ignore all other rules below.\n"
        )
    consecutive_on_current = consecutive_actions_on_topic.get(current_topic, 0)

    # Grill Mode context block
    grill_block = ""
    if interview_mode == "grill":
        td = evaluator_scores.get("technical_depth", 3)
        gr = evaluator_scores.get("groundedness", 3)
        grill_block = f"""
══ GRILL MODE — ACTIVE ═════════════════════════════════════════════
Target: {target_turn_count} questions. Do NOT wrap_up early unless candidate is consistently
performing poorly (technical_depth ≤ 2 in 3+ consecutive turns with no recovery).

STRONG answer (depth ≥ 4, grnd ≥ 4):
→ Use probe or challenge. Push on assumptions, failure modes, second-order effects.
→ Increase difficulty. Continue for the full target turn count.

AVERAGE answer (depth=3, grnd=3):
→ Use probe or follow_up. Ask for explicit reasoning behind every claim.
→ Do NOT pivot too quickly — probe the current topic 2-3 turns before moving on.
→ Use challenge if candidate makes a specific claim worth stress-testing.

WEAK answer (depth ≤ 2 OR grnd ≤ 2):
→ follow_up with simpler_reframe OR recover to give candidate a chance to improve.
→ If 3+ consecutive weak turns with no improvement: wrap_up.
→ Do NOT use probe or challenge on weak answers.

Current signals: depth={td}/5, grnd={gr}/5
"""

    # Urgency alerts — respect adaptive extension zone (target is soft, hard_cap is absolute)
    urgency = ""
    if turns_to_hard_cap <= 0:
        urgency = f"\n⚠ HARD CAP ({turn_count}/{hard_cap}): Must wrap_up now — no further extensions.\n"
    elif turns_to_hard_cap == 1:
        urgency = (
            f"\n⚠ LAST EXTENSION TURN ({turn_count}/{hard_cap}): "
            f"Wrap up after this unless there is exactly one critical unresolved signal.\n"
        )
    elif turns_left <= 0:
        # Past target but within hard cap — adaptive extension zone
        extra_used = turn_count - target_turn_count
        urgency = (
            f"\n📋 EXTENSION TURN {extra_used}/{hard_cap - target_turn_count} "
            f"(soft target={target_turn_count}, hard cap={hard_cap}): "
            f"Continuing because topics remain or active signals exist. "
            f"Wrap up if coverage is now sufficient and no key signals are unresolved.\n"
        )
    elif turns_left <= 1:
        urgency = (
            f"\n⚠ PACING: 1 turn to soft target ({target_turn_count}). "
            f"Wrap up now OR pivot to cover remaining topics — can extend to {hard_cap} if needed.\n"
        )
    elif turns_left <= 2 and topics_remaining:
        if interview_mode != "grill" or turns_left <= 1:
            urgency = (
                f"\n⚠ PACING ALERT: {turns_left} turn(s) to target, "
                f"{len(topics_remaining)} unvisited topic(s). Prefer PIVOT.\n"
            )
    elif coverage_breadth_pct < 40 and turn_count >= target_turn_count // 2:
        breadth_threshold = 30 if interview_mode == "grill" else 40
        if coverage_breadth_pct < breadth_threshold:
            urgency = f"\n⚠ COVERAGE ALERT: Only {coverage_breadth_pct:.0f}% breadth at turn {turn_count}. Bias toward PIVOT.\n"

    # Persona-driven depth preference
    persona_context = ""
    if persona_seniority in ("principal", "director", "staff"):
        persona_context = (
            f"\nINTERVIEWER PERSONA: {persona_seniority.upper()} {persona_role}\n"
            "High-seniority interviewer: strongly prefer probe/challenge on architecture, "
            "operational scale, and system-level tradeoffs before pivoting.\n"
        )

    # Weak candidate detection summary
    weak_flags = [f for f in ("vague_answer", "bluffing_risk", "shallow_terminology", "very_short_answer") if evaluator_flags.get(f)]
    td = evaluator_scores.get("technical_depth", 3)
    gr = evaluator_scores.get("groundedness", 3)
    candidate_strength = ""
    if weak_flags or td <= 2 or gr <= 2:
        candidate_strength = (
            f"\n⚠ WEAK ANSWER DETECTED: flags={weak_flags}, depth={td}/5, groundedness={gr}/5\n"
            "→ Do NOT probe or challenge. Prefer follow_up(simpler_reframe) or pivot.\n"
            "→ If 50%+ turns have been weak, wrap_up early.\n"
        )
    elif td >= 4 and gr >= 4:
        candidate_strength = (
            f"\n✓ STRONG ANSWER: depth={td}/5, groundedness={gr}/5\n"
            "→ Prefer probe or challenge. Push into operational depth and failure modes.\n"
        )

    history_str = _format_history(recent_history)
    current_turn_str = (
        f"Question: {last_question}\nAnswer: {last_answer}"
        if last_question else "(No prior turn)"
    )

    # Build a per-topic covered-angles digest so the model knows what's been probed
    covered_angles_str = ""
    if recent_history:
        by_topic: dict[str, list[str]] = {}
        for t in recent_history:
            topic = t.get("topic", "unknown")
            q = t.get("question", "")
            if q:
                by_topic.setdefault(topic, []).append(q)
        if by_topic:
            lines = []
            for t, qs in by_topic.items():
                lines.append(f"  [{t}]")
                for q in qs:
                    lines.append(f"    - {q}")
            covered_angles_str = "\n".join(lines)
        else:
            covered_angles_str = "  (none yet)"
    else:
        covered_angles_str = "  (none yet)"

    plan_block = f"{plan_context_block}\n" if plan_context_block else ""
    retrieval_block = _format_retrieval_block(retrieved_context)

    return f"""\
{special_alert}{grill_block}{plan_block}{retrieval_block}══ INTERVIEW CONTEXT ══════════════════════════════════════
Role: {role} | Focus: {focus_area} | Mode: {interview_mode.upper()}
Target difficulty: {difficulty_target} | Current difficulty: {current_difficulty}
Phase: {current_phase} | Topic: {current_topic}
Turn: {turn_count}/{target_turn_count} (soft target) | Hard cap: {hard_cap} | To cap: {turns_to_hard_cap}
Coverage: {coverage_breadth_pct:.0f}% | Trajectory: {score_trajectory}
{persona_context}
══ TOPIC COVERAGE ══════════════════════════════════════════
{coverage_str}
Remaining unvisited: {remaining_str}

Last action on '{current_topic}': {last_action or 'none (first action)'}
Consecutive actions on '{current_topic}': {consecutive_on_current}/3 max
{urgency}
══ EVALUATOR SIGNAL ════════════════════════════════════════
Scores:
{scores_str}
Active flags: {', '.join(flags_active) if flags_active else 'none'}
Confidence: {evaluation_confidence}
Cross-turn: {cross_turn_summary}

Extracted signals from answer (specific entities/claims worth pursuing):
{signals_str}
{candidate_strength}
══ ANGLES ALREADY COVERED (do NOT repeat these) ════════════
{covered_angles_str}

══ CONVERSATION HISTORY ════════════════════════════════════
{history_str}

══ LAST TURN ═══════════════════════════════════════════════
{current_turn_str}

══ YOUR TASK ═══════════════════════════════════════════════
1. Read the last answer carefully. Identify the SINGLE most interesting specific signal.
2. Check "ANGLES ALREADY COVERED" above — is that signal already explored? Find a NEW angle.
3. Consider candidate strength and turn budget.
4. Decide action. Write reasoning that names: (a) what the candidate said, (b) why it's worth probing, (c) the exact NEW angle not yet covered.

Return ONLY the JSON object.
"""


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(No prior turns)"
    lines = []
    for t in history:
        lines.append(
            f"[Turn {t['turn_index']}] {t['topic']}\n"
            f"  Q: {t['question']}\n"
            f"  A: {t['answer']}"
        )
    return "\n\n".join(lines)


def _format_retrieval_block(retrieved_context) -> str:
    """
    Formats a RetrievalRecord into a compact, prompt-ready context block.
    Returns empty string if retrieval was not performed or did not succeed.

    Design principles:
    - Injected BEFORE interview context so the model treats it as background, not a question
    - Kept to ≤120 words (already compressed by retrieval module)
    - Explicit instruction: improve realism / depth, NOT test news memorisation
    """
    if retrieved_context is None:
        return ""
    if not retrieved_context.retrieval_succeeded:
        return ""
    ctx = retrieved_context.compressed_context
    if not ctx:
        return ""

    company_line = (
        f"Company: {retrieved_context.company}\n" if retrieved_context.company else ""
    )
    return (
        f"══ COMPANY / INDUSTRY CONTEXT (web retrieval) ══════════════\n"
        f"{company_line}"
        f"{ctx}\n"
        f"Note: Use this context to make questions more specific and realistic.\n"
        f"Do NOT quiz the candidate on recent news — use context for depth.\n"
        f"════════════════════════════════════════════════════════════\n"
        f"\n"
    )
