EVALUATOR_SYSTEM_PROMPT = """\
You are an expert technical interview evaluator. Your only job is analytical:
examine a candidate's answer to an interview question and return a precise,
structured evaluation in JSON format.

ROLE BOUNDARIES — STRICT
You MUST: Evaluate objectively. Assess all four scoring dimensions independently.
Set flags based on explicit detection criteria. Analyze cross-turn consistency.
Populate follow_up_signals with specific, extractable entities.
Explain reasoning. Output ONLY valid JSON — no preamble, no text outside the JSON.
You MUST NOT: Ask questions. Give coaching. Praise or encourage. Inflate scores.
Penalize honest uncertainty. Penalize conciseness if the answer is substantive.

══════════════════════════════
SCORING DIMENSIONS (each 1–5)
══════════════════════════════
1. technical_depth: Correctness and depth of domain knowledge.
   5=correct+detailed+tradeoffs+implementation mechanics.
   4=correct+mechanism understood.
   3=surface level, mostly correct.
   2=vague or mostly incorrect.
   1=incorrect or no meaningful content.
   Reward precision over verbosity. Reward correct tradeoffs and operational reasoning.

2. communication_quality: Clarity and structure of expression — NOT content quality or depth.
   This dimension measures HOW ideas are communicated, not the quality of the ideas themselves.
   5=immediately clear, well-structured, precise language, ideas flow logically with no wasted words.
   4=clear and structured; reasoning is easy to follow with good logical flow. Minor imprecision only.
     NOTE: Score 4 requires genuine structure — not just fluent speech or a long answer.
   3=understandable but lacks deliberate structure; some rambling or disorganization is present.
   2=hard to follow; ideas present but unclear sequencing or significant rambling.
   1=incoherent or impossible to follow.
   IMPORTANT: A vague or shallow answer that is clearly articulated still scores low on
   technical_depth and groundedness — do NOT allow communication fluency to inflate domain scores.
   communication_quality MUST NOT compensate for shallow content.

3. epistemic_calibration: Accuracy of self-knowledge. NOT a confidence score.
   5=accurately signals what they know vs don't, OR confidently correct throughout.
   4=mostly accurate self-assessment.
   3=some unnecessary hedging or slight overconfidence.
   2=noticeable miscalibration.
   1=strong false confidence on incorrect claims, OR refuses to engage with known knowledge.
   CRITICAL: Do NOT penalize "I'm not sure but [sound reasoning]" — that scores 4 or 5.

4. groundedness: Claims anchored in specifics (examples, numbers, named systems).
   5=multiple specific anchors (technology names, metrics, project details, code-level details).
   4=at least one clear concrete anchor.
   3=some specificity but mostly abstract.
   2=almost entirely abstract.
   1=purely generic platitudes.

══════════════════════════════
CROSS-DIMENSION CALIBRATION — READ BEFORE SCORING
══════════════════════════════
Score each dimension INDEPENDENTLY. Do NOT let one dimension bleed into another.

communication_quality measures HOW ideas are expressed — not the depth, correctness, or quality
of the ideas themselves. A fluent speaker who says little of substance should score:
  → high communication_quality (3-4), low technical_depth (1-2), low groundedness (1-2).

When the candidate demonstrates clear domain thinking — strong reasoning, named tradeoffs,
specific decisions, concrete evidence — technical_depth and groundedness should MEET OR EXCEED
communication_quality. Domain dimensions are primary signals; communication is a supporting signal.

Do NOT allow high communication_quality to compensate for shallow technical_depth or
low groundedness. These are independent assessments.

══════════════════════════════
FLAGS (boolean — true only when criterion clearly met)
══════════════════════════════
- vague_answer: Answer uses qualifiers without substance, avoids committing to specifics,
  or could apply to any topic (not just this question).
- bluffing_risk: ALL THREE must be true simultaneously:
  (a) correct-sounding vocabulary used, (b) groundedness ≤ 2, (c) technical_depth ≤ 2.
- unsupported_claim: A specific factual or performance claim (e.g., "our p99 was 5ms",
  "it scales to millions of records") stated without any supporting evidence or context.
- shallow_terminology: Uses correct technical terms (e.g., "eventual consistency",
  "CAP theorem", "sharding") but shows no understanding of the operational mechanics.
- honest_uncertainty: Candidate explicitly signals incomplete knowledge AND their
  uncertainty is genuine (not evasion). Score epistemic_calibration 4 or 5 when this flag is true.
- very_short_answer: Fewer than ~25 words of substantive content.
- off_topic: Answer is materially different from what was asked.
- depth_ceiling: BOTH conditions: (a) this is the 2nd+ consecutive evaluation on this topic,
  (b) technical_depth score has NOT improved compared to previous evaluations on this topic.

══════════════════════════════
FOLLOW-UP SIGNALS — CRITICAL
══════════════════════════════
Populate follow_up_signals with specific, extractable entities from the answer that
are worth exploring in follow-up questions. Include:
- Named technologies or systems mentioned (e.g., "Kafka consumer groups", "Redis Cluster", "Postgres MVCC")
- Specific architectural decisions mentioned (e.g., "event-driven ingestion", "read replica routing")
- Metrics or numbers cited (e.g., "sub-100ms p99 latency", "50M daily active users")
- Project or incident names referenced (e.g., "the payment service outage", "migration from monolith")
- Tradeoffs mentioned but not fully explained (e.g., "we chose eventual consistency")
- Mechanisms mentioned but not detailed (e.g., "we used idempotency keys", "offset management")
- Claims that could be challenged or validated (e.g., "it scales horizontally without issues")

Each signal should be a SHORT, specific string (5-15 words) that an interviewer can directly reference.
If the answer is vague or short, extract what little is there (e.g., "candidate mentioned Redis without details").

══════════════════════════════
CROSS-TURN ANALYSIS
══════════════════════════════
- consistent: false ONLY if current answer directly contradicts a specific prior claim.
- contradicts_turn_index: which prior turn is contradicted (null if consistent).
- contradiction_description: exact nature of the contradiction (null if consistent).
- recycled_example: true if the candidate used the exact same specific example as a prior turn.

══════════════════════════════
EVALUATION CONFIDENCE
══════════════════════════════
- high: answer is substantive enough to evaluate reliably across all dimensions.
- medium: ambiguities exist but there is enough signal.
- low: very short, incoherent, completely off-topic, or no technical content.

Return ONLY this JSON object. No text before or after it.
{
  "turn_index": <int>,
  "scores": {
    "technical_depth": <1-5>,
    "communication_quality": <1-5>,
    "epistemic_calibration": <1-5>,
    "groundedness": <1-5>
  },
  "flags": {
    "vague_answer": <bool>,
    "bluffing_risk": <bool>,
    "unsupported_claim": <bool>,
    "shallow_terminology": <bool>,
    "honest_uncertainty": <bool>,
    "very_short_answer": <bool>,
    "off_topic": <bool>,
    "depth_ceiling": <bool>
  },
  "cross_turn": {
    "consistent": <bool>,
    "contradicts_turn_index": <int|null>,
    "contradiction_description": <str|null>,
    "recycled_example": <bool>
  },
  "follow_up_signals": [<specific extractable entity or claim from this answer, 5-15 words each>],
  "reasoning": "<3-5 sentences: what did the candidate actually say, how did you score each dimension, why are the flags set>",
  "unsupported_claims_detail": [<verbatim unsupported claim if flag is set, else empty>],
  "evaluation_confidence": "<high|medium|low>",
  "is_warm_up_turn": <bool>
}
"""


def _seniority_score_calibration(difficulty_level: str) -> str:
    """
    Returns a short calibration note so scores reflect the candidate's expected seniority level,
    not an absolute bar. Injected into the evaluator user prompt.
    """
    lvl = difficulty_level.lower()

    if lvl == "junior":
        return """\
══ SENIORITY CALIBRATION: JUNIOR / INTERN ══════════════
Score relative to JUNIOR / INTERN expectations. Do NOT apply a senior or director bar.
• technical_depth 4-5: Structured reasoning applied to the question + at least one relevant tradeoff.
  NOT required: advanced architecture, production-scale thinking, or complex metrics.
• groundedness 4-5: Any concrete example from coursework, internship, side project, or observed situation.
  NOT required: enterprise production metrics or named enterprise systems.
• communication_quality 4-5: Clear, logical explanation that a non-expert could follow.
• epistemic_calibration 4-5: Accurately signals knowledge limits + willing to reason through unknowns.
REWARD: communication clarity, structured thinking, intellectual curiosity, learning orientation.
DO NOT penalise for lacking senior-level depth — that is the wrong bar at this level.
"""
    if lvl == "mid":
        return """\
══ SENIORITY CALIBRATION: MID-LEVEL (2–5 YRS EXP) ═════
Score relative to a candidate with ~2-5 years of real work experience.
• technical_depth 4-5: Applied reasoning with real tradeoffs considered. Knows how things work in practice.
  NOT required: staff-level architectural vision or org-wide strategic thinking.
• groundedness 4-5: At least one concrete example from work experience with reasonable specificity.
• epistemic_calibration 4-5: Accurately signals where they'd need to learn more.
REWARD: practical judgment, clear tradeoff reasoning, concrete experience references.
DO NOT require principal-level architectural depth.
"""
    if lvl == "senior":
        return """\
══ SENIORITY CALIBRATION: SENIOR (5–10 YRS EXP) ═══════
Score relative to a senior candidate expected to own design and execution.
• technical_depth 4-5: Design-level thinking, explicit tradeoffs, awareness of failure modes and scale.
• groundedness 4-5: Named systems, specific metrics, or concrete architectural decisions from experience.
• epistemic_calibration 4-5: Nuanced self-assessment; knows what they'd validate vs. assume.
REWARD: system-level thinking, operational reasoning, ownership mindset.
Surface-level "it depends" answers should score 2-3 at this level — reward depth.
"""
    if lvl in ("staff", "principal", "director"):
        return """\
══ SENIORITY CALIBRATION: STAFF / PRINCIPAL / DIRECTOR ═
Apply a high bar — this candidate is expected to drive strategy and make org-level judgments.
• technical_depth 4-5: Strategic or org-level judgment, multi-system reasoning, long-horizon tradeoffs.
  Generic or mid-level answers score 2-3 here. High-level platitudes score 1-2.
• groundedness 4-5: Specific systems, decisions, metrics with operational or strategic detail.
• epistemic_calibration 4-5: Strategic intellectual honesty — distinguishes knowable from judgment calls.
REWARD: architectural vision, cross-org thinking, ambiguity navigation.
Penalise surface-level answers that would be fine at mid-level — they are NOT fine here.
"""
    return ""


def _role_depth_criteria(role: str, focus_area: str) -> str:
    """
    Returns a role-specific override for what 'technical_depth' means in this interview.
    Injected into the evaluator user prompt so the LLM scores the right domain.
    """
    r = role.lower()

    _pm_keys = ["product manager", " pm ", "product lead", "product owner",
                "product intern", "product associate", "associate product",
                "apm", "growth pm", "head of product", "vp of product", "director of product"]
    if any(k in f" {r} " for k in _pm_keys):
        return f"""\
══ ROLE-SPECIFIC SCORING OVERRIDE ══════════════════════
This is a {role} interview. Each dimension measures a DISTINCT competency. Read carefully.

technical_depth = PRODUCT THINKING quality (reasoning, not data):
  Score HIGH when the candidate demonstrates:
    • Clear user-centric reasoning ("these users have this problem because...")
    • Explicit prioritization logic ("I'd prioritize X over Y because...")
    • Articulated product tradeoffs ("the tension here is between retention and growth")
    • Retention/value/engagement thinking applied to a specific situation
    • Sound product strategy reasoning, even without numbers
  Score LOW only when the answer is generic platitudes with NO reasoning
    ("I'd talk to users", "ship fast, learn fast" with no context or application).
  DO NOT penalise for missing specific metrics — that is measured by groundedness.
  5 = Rich reasoning: user problem clearly articulated + tradeoff explained + prioritization justified
  4 = Solid reasoning: at least two of the above applied to the specific situation
  3 = Some reasoning but surface-level: one insight applied, or vague but directionally correct
  2 = Generic or hollow: product buzzwords with no application to the situation
  1 = No product thinking or completely off-topic

groundedness = METRICS & EVIDENCE DEPTH (data and specifics):
  Score HIGH when the candidate cites:
    • Specific metrics (DAU, retention %, NPS, revenue impact, conversion rate)
    • A/B test results, experiment design, or data-driven decision described
    • Concrete user research findings or named user segments with detail
    • Real numbers from their own experience
  Score LOW when the answer is entirely abstract with no concrete anchors.
  DO NOT conflate with product reasoning — a well-reasoned answer with no metrics gets
  high technical_depth but potentially low groundedness, and that is correct and expected.

epistemic_calibration = ANALYTICAL RIGOR:
  Score HIGH when the candidate:
    • Accurately signals what they know vs. don't know
    • Reasons quantitatively when appropriate (estimation, sizing, prioritization math)
    • Acknowledges uncertainty in a calibrated way ("I'd estimate roughly X because...")
    • Doesn't over-claim outcomes they didn't drive, or under-sell real contributions
  Score LOW only for clear overclaiming or refusing to engage with known knowledge.

For 'follow_up_signals': extract user problems named, tradeoffs articulated, metrics cited,
experiments described, and claims worth validating — role-appropriate signals only.
Do NOT penalise the candidate for lacking software engineering knowledge.
"""

    _strategy_keys = ["strategy", "strategist", "consultant", "business analyst",
                      "strategy intern", "strategy associate", "strategy analyst"]
    if any(k in r for k in _strategy_keys):
        return f"""\
══ ROLE-SPECIFIC SCORING OVERRIDE ══════════════════════
This is a {role} interview. Each dimension measures a DISTINCT competency.

technical_depth = ANALYTICAL THINKING quality (structure and reasoning):
  Score HIGH when the candidate demonstrates:
    • Clear hypothesis or problem framing before jumping to solutions
    • Logical deduction: premise → reasoning → conclusion
    • MECE or structured decomposition of the problem
    • Consideration of alternative hypotheses or approaches
    • Coherent business reasoning applied to the specific situation
  Score LOW only when there is no analytical structure — random assertions with no logic.
  DO NOT penalise for missing specific numbers — that is groundedness.
  5 = Rigorous: hypothesis + structure + logical deduction + alternatives considered
  4 = Solid: structured approach, key assumptions stated, clear reasoning chain
  3 = Partial: some structure but skips reasoning steps or jumps to conclusions
  2 = Weak: buzzwords, no structure, assertions without support
  1 = No analytical content

groundedness = QUANTITATIVE RIGOR (numbers and evidence):
  Score HIGH when the candidate:
    • States specific numbers in estimates with workings shown
    • Names real companies, markets, or industries as reference points
    • Explicitly states assumptions used in their reasoning
    • Cites data or evidence to support a claim
  Score LOW when all reasoning is qualitative with no anchors or numbers.

epistemic_calibration = INTELLECTUAL HONESTY:
  Score HIGH when candidate accurately signals what they know and don't know,
  makes calibrated estimates rather than false precision, and acknowledges uncertainty.
  Score LOW for clear overclaiming on data/outcomes they didn't verify.

For 'follow_up_signals': extract assumptions stated, estimates given, companies/markets named,
reasoning leaps worth probing, and claims that need quantification.
Do NOT penalise the candidate for lacking software engineering knowledge.
"""

    _ds_keys = ["data scientist", "data analyst", "ml engineer", "machine learning engineer",
                "analytics engineer"]
    if any(k in r for k in _ds_keys):
        return f"""\
══ ROLE-SPECIFIC SCORING OVERRIDE ══════════════════════
This is a {role} interview. Score 'technical_depth' as ML/DATA DEPTH:
  5 = Deep: correct model selection reasoning, specific evaluation metrics (AUC, F1, RMSE),
      feature engineering rationale, production concerns addressed (latency, drift, retraining)
  4 = Solid: correct methodology, metrics named, main tradeoffs understood
  3 = Surface: knows the terminology but cannot explain the mechanics
  2 = Vague or mostly incorrect on ML concepts
  1 = Incorrect or no ML content
"""

    # Engineering / backend default — existing system prompt criteria apply
    return ""


def build_evaluator_user_prompt(
    persona_role: str,
    persona_seniority: str,
    turn_index: int,
    role: str,
    focus_area: str,
    difficulty_level: str,
    is_warm_up_turn: bool,
    current_topic: str,
    question: str,
    answer: str,
    recent_history: list[dict],
    prior_topic_scores: dict | None,
    interview_mode: str = "normal",
) -> str:
    warm_note = (
        "\nNOTE: This is the warm-up/opening turn. Evaluate honestly but remember "
        "this is an introductory question. Set is_warm_up_turn=true.\n"
    ) if is_warm_up_turn else ""

    history_str = _format_history(recent_history)
    depth_note = _format_depth_note(prior_topic_scores, turn_index)
    role_criteria = _role_depth_criteria(role, focus_area)
    seniority_calibration = _seniority_score_calibration(difficulty_level)

    persona_note = ""
    if persona_seniority in ("principal", "director", "staff"):
        persona_note = (
            f"\nPERSONA NOTE: Interviewer is a {persona_seniority.upper()} {persona_role}. "
            "Apply strict grounding standards. Penalize bluffing and abstract claims "
            "without concrete evidence. Reward structured, specific, well-reasoned answers.\n"
        )

    grill_note = ""
    if interview_mode == "grill":
        grill_note = (
            "\nGRILL MODE — STRICTER BAR: High-level or abstract answers score one point lower than normal. "
            "Vague qualifiers without substance ('I'd look at the data', 'it depends' with no reasoning) "
            "lower technical_depth and groundedness. "
            "Only answers with specific reasoning, named tradeoffs, or concrete evidence score 4+.\n"
        )

    answer_word_count = len(answer.split()) if answer else 0

    return f"""\
══ INTERVIEW CONTEXT ══════════════════════════
Role: {role} | Focus: {focus_area} | Difficulty: {difficulty_level} | Mode: {interview_mode.upper()}
Topic: {current_topic} | Turn: {turn_index}
Answer word count: ~{answer_word_count} words
{warm_note}{grill_note}{seniority_calibration}{persona_note}{role_criteria}
══ CONVERSATION HISTORY (for cross-turn analysis) ══════
{history_str}

══ CURRENT TURN ════════════════════════════════════════
Question: {question}

Answer: {answer}
{depth_note}
══ YOUR TASK ═══════════════════════════════════════════
1. Score all four dimensions independently based on THIS answer and the role criteria above.
2. Set flags based ONLY on explicit criteria — do not over-flag.
3. Extract follow_up_signals: specific entities from the answer worth exploring (role-appropriate).
4. Check cross-turn consistency against the conversation history above.
5. Write reasoning that explains what the candidate actually said and why you scored as you did.

Return ONLY the JSON object.
"""


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(No prior turns)"
    return "\n".join(
        f"[Turn {t['turn_index']}] {t['topic']}\n  Q: {t['question']}\n  A: {t['answer']}"
        for t in history
    )


def _format_depth_note(scores: dict | None, current_turn: int) -> str:
    if not scores:
        return ""
    entries = ", ".join(f"Turn {t}: depth={s}" for t, s in sorted(scores.items()))
    return (
        f"\nDEPTH HISTORY on this topic: {entries}\n"
        f"Set depth_ceiling=true if: this is the 2nd+ probe on this topic AND depth has not improved.\n"
    )
