from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelConfig:
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    temperature: float = 0.3


@dataclass(frozen=True)
class AgentConfigs:
    evaluator: ModelConfig = field(default_factory=lambda: ModelConfig(temperature=0.2))
    strategy: ModelConfig = field(default_factory=lambda: ModelConfig(temperature=0.2))
    interviewer: ModelConfig = field(default_factory=lambda: ModelConfig(temperature=0.7))
    coach: ModelConfig = field(default_factory=lambda: ModelConfig(max_tokens=2048, temperature=0.3))


AGENT_CONFIGS = AgentConfigs()
