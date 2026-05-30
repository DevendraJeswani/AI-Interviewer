import json
import logging
from typing import Optional

from pydantic import ValidationError

from state.models import StrategyDecision
from state.enums import InterviewPhase
from state.defaults import fallback_strategy_decision

logger = logging.getLogger(__name__)


def _extract_json(raw: str) -> Optional[dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        inner = []
        for line in lines[1:]:
            if line.strip() == "```":
                break
            inner.append(line)
        raw = "\n".join(inner).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def validate_strategy_decision(
    raw: str,
    current_topic: str,
    current_phase: InterviewPhase,
) -> tuple[StrategyDecision, bool]:
    parsed = _extract_json(raw)
    if parsed is None:
        logger.warning("[Strategy] JSON extraction failed.")
        return fallback_strategy_decision(current_topic, current_phase), False
    try:
        decision = StrategyDecision(**parsed)
        return decision, True
    except (ValidationError, Exception) as e:
        logger.warning(f"[Strategy] Validation failed: {e}")
        return fallback_strategy_decision(current_topic, current_phase), False
