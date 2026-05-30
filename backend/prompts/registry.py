from dataclasses import dataclass


@dataclass(frozen=True)
class PromptVersion:
    agent: str
    version: str
    description: str

    def __str__(self) -> str:
        return f"{self.agent}-{self.version}"


EVALUATOR_V1 = PromptVersion("signals", "v2.0", "Deterministic signal extractor: heuristic flags + baseline scores. No LLM.")
STRATEGY_V1 = PromptVersion("strategy", "v1.0", "Initial strategy: 5 actions, guardrails.")
INTERVIEWER_V1 = PromptVersion("interviewer", "v1.0", "Initial interviewer: persona card, 3 phases.")
COACH_V1 = PromptVersion("coach", "v1.0", "Initial coach: 2-pass, mandatory citations.")

ACTIVE_VERSIONS = {
    "evaluator": EVALUATOR_V1,
    "strategy": STRATEGY_V1,
    "interviewer": INTERVIEWER_V1,
    "coach": COACH_V1,
}


def get_active_version_string(agent: str) -> str:
    if agent not in ACTIVE_VERSIONS:
        raise ValueError(f"Unknown agent: {agent}")
    return str(ACTIVE_VERSIONS[agent])


def snapshot_all_versions() -> dict[str, str]:
    return {agent: str(v) for agent, v in ACTIVE_VERSIONS.items()}
