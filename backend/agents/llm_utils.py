"""
Shared LLM call utilities: retry logic for Gemini rate limits.
"""
import time
import logging
import re
from typing import Optional, Callable

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [15, 30]  # seconds between retries


def call_with_retry(fn: Callable[[], Optional[str]], agent_name: str) -> Optional[str]:
    """
    Call fn() which makes a Gemini API request. On 429 RESOURCE_EXHAUSTED,
    wait and retry up to len(_RETRY_DELAYS) times. Returns None on final failure.
    """
    last_exc = None
    for attempt, delay in enumerate([-1] + _RETRY_DELAYS):
        if delay >= 0:
            logger.warning(f"[{agent_name}] Rate limited — retrying in {delay}s (attempt {attempt}/{len(_RETRY_DELAYS)})")
            time.sleep(delay)
        try:
            result = fn()
            return result
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                # Try to extract the suggested retry delay from the error message
                match = re.search(r"retry in (\d+)\.?\d*s", err_str)
                if match and attempt == 0:
                    suggested = min(int(match.group(1)), 60)
                    _RETRY_DELAYS[0] = suggested
                last_exc = e
                logger.warning(f"[{agent_name}] 429 rate limit: {err_str[:200]}")
                continue
            if "503" in err_str or "UNAVAILABLE" in err_str:
                # Model temporarily overloaded — retry with short delay
                last_exc = e
                logger.warning(f"[{agent_name}] 503 unavailable — retrying: {err_str[:120]}")
                continue
            # Non-retryable error — log and return None immediately
            logger.error(f"[{agent_name}] Gemini call failed: {e}")
            return None
    logger.error(f"[{agent_name}] All retries exhausted. Last error: {last_exc}")
    return None
