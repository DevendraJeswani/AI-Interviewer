"""
Deterministic role-aware expectations engine for the Coach Intelligence Pass.

Maps role + focus_area combinations to structured coaching expectations used as
context for the LLM contextual analysis pass.

DESIGN PRINCIPLES:
- Completely deterministic — no LLM involved.
- Expectations are coaching GUIDANCE, not hard scoring rules.
- The engine produces context signals; the LLM decides what to use.
- Covers PM, Strategy/Consulting, SWE, DS/ML with focus-area sub-specialisation.
- Alternative valid reasoning paths are explicitly acknowledged.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RoleExpectations:
    role_family: str                                     # e.g. "product_manager"
    primary_label: str                                   # e.g. "Product Manager"
    primary_competencies: list[str] = field(default_factory=list)
    concept_signals: list[str] = field(default_factory=list)   # what strong answers show
    tradeoff_areas: list[str] = field(default_factory=list)    # expected tradeoff discussions
    metric_areas: list[str] = field(default_factory=list)      # metric reasoning expected
    reasoning_patterns: list[str] = field(default_factory=list)  # expected reasoning styles
    role_fit_signals: list[str] = field(default_factory=list)    # positive role-fit markers


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def build_role_expectations(role: str, focus_area: str, difficulty: str) -> RoleExpectations:
    """
    Build role-specific coaching expectations for a given role + focus area.
    Returns deterministic guidance — no LLM involved.
    """
    r = role.lower()
    f = focus_area.lower()

    _pm_keys = [
        "product manager", " pm ", "product lead", "product owner",
        "product intern", "product associate", "associate product",
        "apm", "growth pm", "head of product", "vp of product", "director of product",
    ]
    if any(k in f" {r} " for k in _pm_keys):
        return _pm_expectations(r, f, difficulty)

    _strategy_keys = [
        "strategy", "strategist", "consultant", "business analyst",
        "strategy intern", "strategy associate", "strategy analyst",
    ]
    if any(k in r for k in _strategy_keys):
        return _strategy_expectations(r, f, difficulty)

    _ds_keys = [
        "data scientist", "data analyst", "ml engineer", "machine learning engineer",
        "analytics engineer", "machine learning",
    ]
    if any(k in r for k in _ds_keys):
        return _ds_expectations(r, f, difficulty)

    return _swe_expectations(r, f, difficulty)


def format_expectations_block(exp: RoleExpectations) -> str:
    """
    Format RoleExpectations as a structured text block for LLM prompt injection.
    """
    lines = [
        f"ROLE COACHING EXPECTATIONS — {exp.primary_label}",
        "",
        "Primary competencies being assessed:",
    ]
    for c in exp.primary_competencies:
        lines.append(f"  * {c}")

    lines += [
        "",
        "Concept signals that STRONG answers typically show (reasoning patterns, NOT required keywords):",
    ]
    for s in exp.concept_signals:
        lines.append(f"  * {s}")

    if exp.tradeoff_areas:
        lines += ["", "Tradeoff reasoning areas expected for this role/focus:"]
        for t in exp.tradeoff_areas:
            lines.append(f"  * {t}")

    if exp.metric_areas:
        lines += ["", "Quantitative / metric reasoning expected:"]
        for m in exp.metric_areas:
            lines.append(f"  * {m}")

    if exp.reasoning_patterns:
        lines += ["", "Reasoning patterns expected at this level:"]
        for p in exp.reasoning_patterns:
            lines.append(f"  * {p}")

    if exp.role_fit_signals:
        lines += ["", "Positive role-fit markers (genuine role-thinking, not buzzwords):"]
        for s in exp.role_fit_signals:
            lines.append(f"  * {s}")

    lines += [
        "",
        "REMINDER: These are coaching signals — not keyword requirements.",
        "A candidate who shows the right REASONING without exact terminology should be credited.",
        "Equivalent concepts and alternative valid approaches must be recognised.",
    ]
    return "\n".join(lines)


def select_turns_for_context_analysis(turns_data: list[dict], max_turns: int = 3) -> list[dict]:
    """
    Select the most coaching-relevant turns from the serialized turns list.
    Prioritises weaker/moderate turns (where coaching insight adds most value).
    Excludes warm-up turns.
    Returns turns sorted by original turn_index (chronological).
    """
    substantive = [t for t in turns_data if not t.get("is_warm_up")]
    if not substantive:
        substantive = turns_data

    def _combined(t: dict) -> float:
        s = t.get("scores", {})
        td = s.get("technical_depth", 3)
        gr = s.get("groundedness", 3)
        ec = s.get("epistemic_calibration", 3)
        return td * 0.4 + gr * 0.4 + ec * 0.2

    sorted_turns = sorted(substantive, key=_combined)
    selected = sorted_turns[:min(max_turns, len(sorted_turns))]
    selected.sort(key=lambda t: t.get("turn_index", 0))
    return selected


# ─────────────────────────────────────────────────────────────────────────────
# Role-specific expectation builders
# ─────────────────────────────────────────────────────────────────────────────

def _pm_expectations(role: str, focus_area: str, difficulty: str) -> RoleExpectations:
    is_growth   = any(k in focus_area for k in ["growth", "acquisition", "retention", "activation", "funnel"])
    is_platform = any(k in focus_area for k in ["platform", "api", "infrastructure", "developer", "ecosystem"])
    is_data     = any(k in focus_area for k in ["data", "analytics", "ml", "machine learning", "ai"])
    is_b2b      = any(k in focus_area for k in ["enterprise", "b2b", "saas", "sales", "gtm"])
    is_ops      = any(k in focus_area for k in ["ops", "operations", "operational", "supply", "process"])

    concept_signals = [
        "Customer problem framing before jumping to solution",
        "Explicit prioritization logic with reasoning (why this over alternatives)",
        "Success metric tied to user behaviour or business outcome — not just output shipped",
        "Tradeoff acknowledgment — what you are NOT doing and why",
        "Execution awareness: rollout plan, risks, dependencies, stakeholder alignment",
    ]
    metric_areas = [
        "User engagement metrics (DAU, WAU, retention rate, activation rate)",
        "Business impact metrics (revenue, NPS, conversion rate, LTV)",
        "Counter-metrics (what would signal unintended harm from the change)",
    ]
    tradeoff_areas = [
        "Short-term user delight vs. long-term product health",
        "Feature breadth vs. depth for a target segment",
        "Speed of delivery vs. quality / debt incurred",
        "Which user segment to optimise for and who gets deprioritised",
    ]
    reasoning_patterns = [
        "Problem definition -> user segmentation -> metric -> solution -> tradeoffs",
        "Customer evidence-based decisions (data or research, not pure assumption)",
        "Data-informed judgment — knows what the data says AND applies judgment",
        "Cross-functional awareness: eng constraints, design, legal, GTM",
    ]
    role_fit_signals = [
        "Talks about users with specificity — segment, behaviour, pain, not generic 'users'",
        "Anchors product decisions in measurable outcomes, not features shipped",
        "Shows awareness of what they're not doing and the opportunity cost",
        "Uses product reasoning vocabulary naturally without being formulaic",
    ]

    if is_growth:
        concept_signals += [
            "Funnel stage thinking: acquisition, activation, retention, referral, revenue",
            "Experiment / A-B test design: hypothesis, metric, control, guardrail",
            "Cohort retention analysis and activation vs. engagement distinction",
        ]
        metric_areas += [
            "Funnel conversion rate at each stage, activation rate, D30/D90 retention",
            "LTV / CAC reasoning and payback period",
            "Experiment success metric and minimum detectable effect size",
        ]

    elif is_platform:
        concept_signals += [
            "Developer experience reasoning: time-to-first-call, error clarity, SDK quality",
            "Scalability and reliability tradeoffs (SLOs, error budgets)",
            "Ecosystem and partner thinking — not just internal users",
        ]
        metric_areas += [
            "API adoption rate, developer NPS, time-to-integration",
            "Platform reliability: p99 latency, error rate, uptime SLO",
        ]

    elif is_b2b:
        concept_signals += [
            "Buyer vs. end-user distinction (who decides, who uses, who pays)",
            "Sales cycle awareness: deal size, procurement, integration constraints",
            "Stakeholder mapping: champion, economic buyer, technical evaluator, blocker",
        ]

    elif is_ops:
        concept_signals += [
            "Operational efficiency metrics and process bottleneck identification",
            "Change management and adoption planning",
            "Cost vs. quality tradeoffs in operational decisions",
        ]

    return RoleExpectations(
        role_family="product_manager",
        primary_label="Product Manager",
        primary_competencies=[
            "Product thinking depth (problem framing, prioritisation, strategy)",
            "Data-driven decision making (metric definition and use)",
            "Customer empathy and segmentation specificity",
            "Execution awareness and tradeoff reasoning",
            "Cross-functional alignment and stakeholder management",
        ],
        concept_signals=concept_signals,
        tradeoff_areas=tradeoff_areas,
        metric_areas=metric_areas,
        reasoning_patterns=reasoning_patterns,
        role_fit_signals=role_fit_signals,
    )


def _strategy_expectations(role: str, focus_area: str, difficulty: str) -> RoleExpectations:
    is_corp   = any(k in focus_area for k in ["corporate", "corp strat", "m&a", "acquisition", "merger"])
    is_market = any(k in focus_area for k in ["market", "go-to-market", "gtm", "competitive"])
    is_ops    = any(k in focus_area for k in ["operations", "operational", "ops", "process"])

    concept_signals = [
        "MECE problem decomposition before diving into analysis",
        "Explicit hypothesis formation — state the hypothesis, then test it",
        "Issue tree or structured breakdown of the problem space",
        "Assumption identification and quantification (show the math)",
        "Evidence-based conclusion — not assertion-only reasoning",
        "Recommendation with named tradeoffs and risks",
    ]
    tradeoff_areas = [
        "Speed vs. accuracy of analysis in time-constrained decisions",
        "Short-term revenue vs. long-term market position",
        "Organic vs. inorganic growth (build vs. acquire)",
        "Centralisation vs. decentralisation of operations",
    ]
    metric_areas = [
        "Market size estimation (TAM/SAM/SOM) with explicit step-by-step assumptions",
        "Unit economics: margin, contribution margin, LTV/CAC, payback period",
        "Growth rates with named comparable benchmark companies or markets",
        "Quantified business impact of the recommendation",
    ]
    reasoning_patterns = [
        "Lead with the hypothesis — don't bury the recommendation",
        "Show your work in estimation: step-by-step, not just final number",
        "Acknowledge uncertainty — quantify it where possible",
        "Name specific companies, markets, or cases as grounding evidence",
        "Structure the answer before diving into detail (don't data-dump)",
    ]
    role_fit_signals = [
        "Leads with structured framing before diving into analysis",
        "Uses numbers to support qualitative claims",
        "Names specific companies, sectors, or transactions as evidence",
        "Shows intellectual humility about assumptions and where analysis could be wrong",
    ]

    if is_corp:
        concept_signals += [
            "M&A strategic rationale: synergies, integration risk, valuation logic",
            "Portfolio strategy thinking: core vs. adjacent vs. new markets",
        ]
    elif is_market:
        concept_signals += [
            "Competitive positioning: differentiation, moat, defensibility",
            "Channel strategy and distribution reasoning",
            "Customer segmentation and willingness-to-pay reasoning",
        ]

    return RoleExpectations(
        role_family="strategy_consulting",
        primary_label="Strategy / Consulting",
        primary_competencies=[
            "Structured problem decomposition (MECE thinking)",
            "Hypothesis-driven analysis",
            "Quantitative estimation and business reasoning",
            "Executive communication clarity",
            "Intellectual honesty about assumptions and uncertainty",
        ],
        concept_signals=concept_signals,
        tradeoff_areas=tradeoff_areas,
        metric_areas=metric_areas,
        reasoning_patterns=reasoning_patterns,
        role_fit_signals=role_fit_signals,
    )


def _ds_expectations(role: str, focus_area: str, difficulty: str) -> RoleExpectations:
    is_ml       = any(k in role for k in ["ml", "machine learning", "deep learning", "nlp"])
    is_analytics = any(k in role for k in ["analyst", "analytics"])

    concept_signals = [
        "Experiment design: control group, randomisation, hypothesis statement",
        "Metric selection rationale — why this metric captures the business goal",
        "Statistical significance and power awareness (sample size, alpha, MDE)",
        "Model evaluation beyond accuracy: precision/recall, AUC, calibration",
        "Data quality and potential leakage identification",
        "Production ML concerns: latency, drift, monitoring, retraining triggers",
    ]
    if is_ml:
        concept_signals += [
            "Feature engineering rationale and leakage risk identification",
            "Model selection reasoning: why this model family for this problem",
            "Regularisation and overfitting vs. underfitting tradeoffs",
            "Fairness and bias awareness in model design and evaluation",
        ]
    if is_analytics:
        concept_signals += [
            "Funnel analysis and cohort segmentation",
            "Causality vs. correlation distinction and how to test",
            "Leading vs. lagging indicator selection for dashboards",
        ]

    tradeoff_areas = [
        "Interpretability vs. predictive accuracy",
        "Latency vs. model complexity in production",
        "Online vs. offline evaluation — knowing the gap between them",
        "Precision vs. recall and the business cost of each error type",
    ]
    metric_areas = [
        "Evaluation metrics: AUC-ROC, F1, RMSE, MAPE, precision@k",
        "Business metrics connected to model outcomes (revenue, engagement, churn)",
        "Experiment metrics: p-value, confidence interval, minimum detectable effect",
        "Production metrics: latency p99, throughput, model drift indicators",
    ]
    reasoning_patterns = [
        "Problem -> data -> model -> evaluation -> deployment -> monitoring flow",
        "State distribution assumptions about data explicitly",
        "Connect model metric to business metric — don't stop at technical performance",
        "Identify failure modes proactively (what could go wrong in production)",
    ]
    role_fit_signals = [
        "Discusses data limitations and what they'd do about them",
        "Mentions validation strategy unprompted",
        "Distinguishes research prototype from production system",
        "Connects technical decisions back to business outcomes",
    ]

    return RoleExpectations(
        role_family="data_science_ml",
        primary_label="Data Science / ML",
        primary_competencies=[
            "ML/statistical methodology depth",
            "Experimental design and evaluation rigour",
            "Data intuition and quality awareness",
            "Production ML system awareness",
            "Business-to-technical translation",
        ],
        concept_signals=concept_signals,
        tradeoff_areas=tradeoff_areas,
        metric_areas=metric_areas,
        reasoning_patterns=reasoning_patterns,
        role_fit_signals=role_fit_signals,
    )


def _swe_expectations(role: str, focus_area: str, difficulty: str) -> RoleExpectations:
    is_backend  = any(k in focus_area for k in ["backend", "back-end", "distributed", "system", "api", "database", "infra"])
    is_frontend = any(k in focus_area for k in ["frontend", "front-end", "ui", "react", "web", "browser"])
    is_mobile   = any(k in focus_area for k in ["mobile", "ios", "android", "react native"])
    is_infra    = any(k in focus_area for k in ["infrastructure", "devops", "platform", "reliability", "sre", "cloud"])

    concept_signals = [
        "Requirements and constraints clarification before jumping to design",
        "Scale assumptions made explicit: expected QPS, data volume, user count",
        "Data modelling reasoning: schema, indexing, normalisation tradeoffs",
        "Failure mode identification and resilience / graceful degradation planning",
        "Operational concerns: monitoring, alerting, on-call, SLOs, runbooks",
    ]
    if is_backend or not (is_frontend or is_mobile or is_infra):
        concept_signals += [
            "Horizontal vs. vertical scaling and when each applies",
            "Caching strategy with invalidation approach and consistency implications",
            "Database selection rationale: read/write patterns, consistency, scale needs",
            "Async/queue-based processing for throughput and decoupling",
        ]
    if is_frontend:
        concept_signals += [
            "Component architecture and state management strategy",
            "Performance: bundle size, rendering cost, lazy loading, caching headers",
            "Accessibility and progressive enhancement awareness",
        ]
    if is_infra:
        concept_signals += [
            "Infrastructure-as-code and change management discipline",
            "Blast radius and rollback strategy for deployments",
            "Cost optimisation vs. reliability tradeoffs",
        ]

    tradeoff_areas = [
        "Consistency vs. availability (CAP theorem)",
        "Latency vs. throughput under load",
        "Storage cost vs. query performance",
        "Build in-house vs. use managed/cloud service",
        "Simplicity now vs. extensibility for future requirements",
    ]
    metric_areas = [
        "Latency targets: p50, p95, p99 — not just averages",
        "Throughput and peak QPS handling capacity",
        "Availability SLO (nines) and error budget implications",
        "Error rate, failure budget, and on-call severity thresholds",
    ]
    reasoning_patterns = [
        "Requirements -> constraints -> options -> tradeoffs -> decision flow",
        "State scale assumptions before designing — they drive all decisions",
        "Explain WHY, not just WHAT you'd build",
        "Identify failure modes and mitigations proactively",
        "Show awareness of operational burden after launch, not just initial build",
    ]
    role_fit_signals = [
        "States scale assumptions explicitly before designing",
        "Identifies tradeoffs without being prompted",
        "Discusses post-launch operational concerns",
        "Uses specific technology names with justification (not just category labels)",
    ]

    return RoleExpectations(
        role_family="software_engineering",
        primary_label="Software Engineering",
        primary_competencies=[
            "Technical design and architectural depth",
            "System-level thinking under realistic scale",
            "Tradeoff analysis and explicit decision-making",
            "Operational and reliability awareness",
            "Implementation specificity (not just high-level concepts)",
        ],
        concept_signals=concept_signals,
        tradeoff_areas=tradeoff_areas,
        metric_areas=metric_areas,
        reasoning_patterns=reasoning_patterns,
        role_fit_signals=role_fit_signals,
    )
