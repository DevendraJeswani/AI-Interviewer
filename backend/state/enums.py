from enum import Enum


class NextAction(str, Enum):
    PROBE = "probe"
    PIVOT = "pivot"
    FOLLOW_UP = "follow_up"
    RECOVER = "recover"
    WRAP_UP = "wrap_up"
    CHALLENGE = "challenge"



class FollowUpIntent(str, Enum):
    VALIDATE_CLAIM = "validate_claim"
    CLARIFY_VAGUENESS = "clarify_vagueness"
    EXPLORE_STORY = "explore_story"
    TEST_BOUNDARY = "test_boundary"
    SIMPLER_REFRAME = "simpler_reframe"
    NONE = "none"


class DifficultyLevel(str, Enum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    PRINCIPAL = "principal"
    DIRECTOR = "director"


class DifficultyAdjustment(str, Enum):
    INCREASE = "increase"
    HOLD = "hold"
    DECREASE = "decrease"
    NONE = "none"


class InterviewPhase(str, Enum):
    OPENING = "opening"
    QUESTIONING = "questioning"
    CLOSING = "closing"
    REPORTING = "reporting"


class ScoreTrajectory(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"
    INSUFFICIENT_DATA = "insufficient_data"


class TopicStatus(str, Enum):
    UNVISITED = "unvisited"
    VISITED = "visited"
    DEPTH_CEILING = "depth_ceiling"
    SKIPPED = "skipped"


class EvaluationConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
