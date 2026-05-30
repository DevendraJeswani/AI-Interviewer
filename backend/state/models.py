from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from .enums import (
    NextAction, FollowUpIntent, DifficultyLevel, DifficultyAdjustment,
    InterviewPhase, ScoreTrajectory, TopicStatus, EvaluationConfidence,
)


class PromptVersions(BaseModel, frozen=True):
    evaluator: str
    strategy: str
    interviewer: str


class PersonaCard(BaseModel, frozen=True):
    role: str = "Engineering Manager"
    seniority: DifficultyLevel = DifficultyLevel.DIRECTOR
    years_of_experience: int = 12
    domain: str
    style: str = "Direct but not cold. Technically precise. Asks one question at a time."


class ImmutableContext(BaseModel, frozen=True):
    session_id: str
    role: str
    focus_area: str
    candidate_background: str
    difficulty_target: DifficultyLevel
    target_turn_count: int = Field(default=6, ge=4, le=14)
    warm_up_score_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    topic_list: list[str]
    persona_card: PersonaCard
    interview_mode: str = "normal"  # "normal" | "grill"


class EvaluatorScores(BaseModel):
    technical_depth: int = Field(..., ge=1, le=5)
    communication_quality: int = Field(..., ge=1, le=5)
    epistemic_calibration: int = Field(..., ge=1, le=5)
    groundedness: int = Field(..., ge=1, le=5)


class CrossTurnAnalysis(BaseModel):
    consistent: bool
    contradicts_turn_index: Optional[int] = None
    contradiction_description: Optional[str] = None
    recycled_example: bool = False


class EvaluatorFlags(BaseModel):
    vague_answer: bool = False
    bluffing_risk: bool = False
    unsupported_claim: bool = False
    shallow_terminology: bool = False
    honest_uncertainty: bool = False
    very_short_answer: bool = False
    off_topic: bool = False
    depth_ceiling: bool = False


class EvaluatorOutput(BaseModel):
    turn_index: int
    scores: EvaluatorScores
    flags: EvaluatorFlags
    cross_turn: CrossTurnAnalysis
    follow_up_signals: list[str] = Field(default_factory=list)
    reasoning: str
    unsupported_claims_detail: list[str] = Field(default_factory=list)
    evaluation_confidence: EvaluationConfidence
    is_warm_up_turn: bool = False


class StrategyDecision(BaseModel):
    next_action: NextAction
    target_topic: str
    difficulty_adjustment: DifficultyAdjustment
    follow_up_intent: FollowUpIntent
    interview_phase: InterviewPhase
    reasoning: str


class TurnRecord(BaseModel):
    turn_index: int
    phase: InterviewPhase
    topic: str
    question: str
    answer: str
    evaluator_output: EvaluatorOutput
    strategy_decision: StrategyDecision
    prompt_versions: PromptVersions
    timestamp: datetime = Field(default_factory=lambda: datetime.utcnow())


class AggregateScores(BaseModel):
    technical_depth: float = 0.0
    communication_quality: float = 0.0
    epistemic_calibration: float = 0.0
    groundedness: float = 0.0


class DerivedSignals(BaseModel):
    topic_coverage: dict[str, TopicStatus] = Field(default_factory=dict)
    aggregate_scores: AggregateScores = Field(default_factory=AggregateScores)
    score_trajectory: ScoreTrajectory = ScoreTrajectory.INSUFFICIENT_DATA
    depth_ceilings: list[str] = Field(default_factory=list)
    consecutive_actions_on_topic: dict[str, int] = Field(default_factory=dict)
    current_difficulty: DifficultyLevel = DifficultyLevel.MID
    topics_remaining: list[str] = Field(default_factory=list)
    turn_count: int = 0
    coverage_breadth_pct: float = 0.0


class EvaluatorToStrategy(BaseModel):
    flags: EvaluatorFlags
    follow_up_signals: list[str]
    evaluation_confidence: EvaluationConfidence
    cross_turn: CrossTurnAnalysis
    reasoning_summary: str


class StrategyToInterviewer(BaseModel):
    next_action: NextAction
    target_topic: str
    follow_up_intent: FollowUpIntent
    difficulty_adjustment: DifficultyAdjustment
    interview_phase: InterviewPhase
    reasoning: str


class AgentMailboxes(BaseModel):
    evaluator_to_strategy: Optional[EvaluatorToStrategy] = None
    strategy_to_interviewer: Optional[StrategyToInterviewer] = None


class CompetencyNote(BaseModel):
    """Tracks per-topic evidence gathered about a candidate."""
    area: str
    turns_explored: int = 0
    avg_technical_score: float = 0.0
    avg_grounding_score: float = 0.0
    has_strong_evidence: bool = False
    strong_evidence_excerpt: str = ""
    recurring_weakness: str = ""
    is_sufficiently_explored: bool = False


class CandidateMemory(BaseModel):
    """Cross-turn memory of observed candidate patterns."""
    strong_moments: list[str] = Field(default_factory=list)
    weak_patterns: list[str] = Field(default_factory=list)
    vague_patterns: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    overused_phrases: list[str] = Field(default_factory=list)
    confidence_trend: str = "unknown"   # "improving" | "declining" | "stable" | "unknown"
    bluffing_incidents: int = 0
    honest_uncertainty_count: int = 0


class InterviewPlan(BaseModel):
    """
    Persistent strategic plan maintained across turns.
    Updated deterministically each turn; LLM reflection every 3 turns.
    """
    active_objectives: list[str] = Field(default_factory=list)
    completed_objectives: list[str] = Field(default_factory=list)
    competency_notes: list[CompetencyNote] = Field(default_factory=list)
    candidate_memory: CandidateMemory = Field(default_factory=CandidateMemory)
    difficulty_trajectory: str = "stable"   # "increasing" | "decreasing" | "stable"
    target_pressure: float = 0.3            # 0.0 = gentle, 1.0 = maximum pressure
    current_pressure: float = 0.3
    turns_since_last_reflection: int = 0
    last_reflection_notes: str = ""
    reflection_flags: list[str] = Field(default_factory=list)
    plan_version: int = 0
    initialized: bool = False


class ConversationalState(BaseModel):
    """
    Per-turn state of the interviewer's conversational stance.
    Updated deterministically after each evaluated turn.
    """
    tone: str = "neutral"                       # "warm" | "neutral" | "skeptical" | "direct"
    pressure_level: float = 0.0                 # 0.0–1.0
    active_strategy: str = "follow_plan"        # label for current conversational posture
    angles_attempted: list[str] = Field(default_factory=list)
    consecutive_weak_turns: int = 0
    consecutive_strong_turns: int = 0
    candidate_confidence_read: str = "unknown"  # "confident" | "uncertain" | "guessing" | "unknown"


class RetrievalRecord(BaseModel):
    """
    Cached web-retrieval result stored in InterviewState.
    Populated at most once per session by the Strategy Agent retrieval module.
    """
    session_id: str
    company: Optional[str] = None
    retrieved_topics: list[str] = Field(default_factory=list)
    summaries: list[str] = Field(default_factory=list)
    timestamps: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    compressed_context: str = ""   # ≤120 words, ready to inject into prompts
    retrieval_attempted: bool = False
    retrieval_succeeded: bool = False


class InterviewState(BaseModel):
    context: ImmutableContext
    turns: list[TurnRecord] = Field(default_factory=list)
    derived: DerivedSignals = Field(default_factory=DerivedSignals)
    mailboxes: AgentMailboxes = Field(default_factory=AgentMailboxes)
    current_phase: InterviewPhase = InterviewPhase.OPENING
    current_topic: str = ""
    current_question: str = ""
    current_answer: str = ""
    is_complete: bool = False
    # ── Agentic planning layer (optional — None until init_node runs) ──────────
    interview_plan: Optional[InterviewPlan] = None
    conversational_state: Optional[ConversationalState] = None
    # ── Web retrieval cache (optional — None until first retrieval succeeds) ───
    retrieved_context: Optional[RetrievalRecord] = None
    # ── Character persona conditioning (optional — populated at session start) ──
    # Structured PersonaConditioningBlock dict from persona_retrieval.py.
    # None when no persona was requested. Injected into every interviewer prompt.
    character_persona: Optional[dict] = None
from dataclasses import dataclass


@dataclass
class GuardrailResult:
    decision: StrategyDecision
    overrides_applied: list[str]
    was_overridden: bool



def safe_rehydrate(raw, model_class):
    """Safely converts a dictionary back to a pydantic model if needed."""
    if isinstance(raw, model_class):
        return raw
    if isinstance(raw, dict):
        try:
            return model_class.model_validate(raw)
        except Exception:
            return None
    return None


def safe_attr(obj, attr_name, default=None):
    """Safely retrieves an attribute whether obj is a model instance or a dict."""
    if hasattr(obj, attr_name):
        return getattr(obj, attr_name)
    if isinstance(obj, dict):
        return obj.get(attr_name, default)
    return default
