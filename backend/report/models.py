from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field
from state.enums import ScoreTrajectory
from state.models import AggregateScores


class TurnEvidence(BaseModel):
    turn_index: int
    excerpt: str
    relevance: str


class FeedbackPoint(BaseModel):
    observation: str
    evidence: list[TurnEvidence] = Field(default_factory=list)
    suggestion: str


class ScoreSummary(BaseModel):
    scores: AggregateScores
    trajectory: ScoreTrajectory
    strongest_dimension: str
    weakest_dimension: str


class TopicCoverageSummary(BaseModel):
    topic: str
    status: str
    turns_spent: int
    peak_depth_score: Optional[int] = None
    summary: str = ""


class CoachReport(BaseModel):
    session_id: str
    role: str
    focus_area: str
    total_turns: int
    interview_duration_approx: str

    overall_summary: str
    score_summary: ScoreSummary

    strengths: list[FeedbackPoint]
    improvement_areas: list[FeedbackPoint]

    communication_feedback: FeedbackPoint
    technical_feedback: FeedbackPoint
    behavioral_feedback: Optional[FeedbackPoint] = None

    practice_recommendations: list[str] = Field(default_factory=list, max_length=3)
    topic_coverage: list[TopicCoverageSummary]
    transcript_highlights: list[TurnEvidence]

    generated_at: str
    prompt_version_coach: str
