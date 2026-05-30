"""
Strategy Agent Web Retrieval Module
=====================================
Provides controlled, cached, and compressed web context to the Strategy Agent.

Trigger logic
-------------
- Fires at most ONCE per session (checked during turns 0-2 only)
- Only for company-specific, industry-trend, or recent-event contexts
- NOT for generic behavioral / product-metrics / estimation questions

Provider hierarchy
------------------
  TAVILY_API_KEY  →  SERPER_API_KEY  →  DuckDuckGo instant-answer (free fallback)

Output
------
A RetrievalRecord is stored in InterviewState.retrieved_context and injected
as a compact ≤120-word block into the Strategy Agent prompt.
Graceful degradation: any failure leaves retrieved_context=None and the
interview continues normally.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from state.models import RetrievalRecord

logger = logging.getLogger(__name__)

# ── Tuning constants ───────────────────────────────────────────────────────────
_MAX_SNIPPETS = 5           # max snippets collected across all queries
_COMPRESS_MAX_TOKENS = 350  # Gemini output budget for compression call
_HTTP_TIMEOUT = 6.0         # seconds — fail fast if provider is slow

# Earliest turn at which retrieval is allowed (0-indexed)
_RETRIEVAL_WINDOW_MAX_TURN = 2  # only consider at turns 0, 1, 2

# ── Low-quality domains to exclude ─────────────────────────────────────────────
_BLOCKED_DOMAINS = {
    "quora.com", "reddit.com", "slideshare.net", "scribd.com",
    "academia.edu", "pinterest.com", "instagram.com", "twitter.com",
    "tiktok.com", "youtube.com",
}

# ── Focus-area keywords that signal generic questions (no retrieval needed) ────
_GENERIC_FOCUS_AREAS = {
    "behavioral", "leadership", "communication", "teamwork", "general",
    "problem solving", "estimation", "guesstimate",
}


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_retrieval_if_needed(state) -> Optional[RetrievalRecord]:
    """
    Main entry point called by strategy_node before each LLM decision.

    Returns
    -------
    RetrievalRecord  – if new retrieval was performed (success or attempted)
    None             – if retrieval is skipped (cache hit, too late in session,
                       or not needed for this interview type)

    The caller should use:
        new_retrieval = run_retrieval_if_needed(state)
        effective_retrieval = new_retrieval or state.retrieved_context
    """
    # Cache hit — reuse existing retrieval, no new fetch needed
    if state.retrieved_context is not None:
        return None

    # Only attempt during the early turns window
    turn_count = len(state.turns)
    if turn_count > _RETRIEVAL_WINDOW_MAX_TURN:
        return None

    ctx = state.context
    session_id = ctx.session_id
    role = ctx.role
    focus_area = ctx.focus_area
    candidate_background = ctx.candidate_background

    company = _extract_company(role, focus_area, candidate_background)
    if not _assess_retrieval_need(focus_area, company, candidate_background):
        logger.info(f"[Retrieval] Skipping — generic context (focus='{focus_area}')")
        return None

    logger.info(
        f"[Retrieval] Triggered — session={session_id} "
        f"company={company!r} focus='{focus_area}'"
    )

    record = RetrievalRecord(
        session_id=session_id,
        company=company,
        retrieval_attempted=True,
    )

    try:
        queries = _build_queries(company, focus_area, role)
        snippets: list[dict] = []
        sources: list[str] = []
        topics: list[str] = []
        timestamps: list[str] = []
        now_str = datetime.now(timezone.utc).strftime("%Y-%m")

        for query in queries:
            results = _search(query)
            for r in results:
                domain = _extract_domain(r.get("url", ""))
                if domain in _BLOCKED_DOMAINS:
                    continue
                snippets.append(r)
                sources.append(r.get("url", ""))
                timestamps.append(r.get("date", now_str))
                topics.append(query)
                if len(snippets) >= _MAX_SNIPPETS:
                    break
            if len(snippets) >= _MAX_SNIPPETS:
                break

        if not snippets:
            logger.info(f"[Retrieval] No usable results for session={session_id}")
            return record  # retrieval_succeeded stays False

        compressed = _compress(snippets, company, focus_area, role)
        summaries = [s.get("snippet", "") for s in snippets]

        record = record.model_copy(update={
            "retrieved_topics": topics[:_MAX_SNIPPETS],
            "summaries": summaries[:_MAX_SNIPPETS],
            "timestamps": timestamps[:_MAX_SNIPPETS],
            "sources": [s for s in sources if s][:_MAX_SNIPPETS],
            "compressed_context": compressed,
            "retrieval_succeeded": bool(compressed),
        })
        word_count = len(compressed.split()) if compressed else 0
        logger.info(
            f"[Retrieval] Done — {len(snippets)} snippets → "
            f"{word_count} words compressed | session={session_id}"
        )

    except Exception as exc:
        logger.warning(f"[Retrieval] Failed (non-fatal): {exc}")

    return record


# ─────────────────────────────────────────────────────────────────────────────
# Trigger heuristics
# ─────────────────────────────────────────────────────────────────────────────

def _assess_retrieval_need(
    focus_area: str,
    company: Optional[str],
    candidate_background: str,
) -> bool:
    """
    Returns True if web retrieval would meaningfully improve interview quality.

    Priority order:
    1. Specific company identified → always retrieve
    2. Generic focus area → never retrieve
    3. Industry-specific focus area → retrieve
    4. Candidate background mentions specific employers → retrieve
    """
    # Company context → always retrieve
    if company:
        return True

    fa_lower = focus_area.lower()

    # Generic focus areas → never retrieve
    for generic in _GENERIC_FOCUS_AREAS:
        if generic in fa_lower:
            return False

    # Industry-specific trigger keywords
    industry_triggers = [
        "fintech", "healthtech", "edtech", "proptech", "insurtech",
        "ai product", "ml product", "platform", "marketplace", "saas",
        "social", "gaming", "e-commerce", "ecommerce", "consumer",
        "developer tools", "infrastructure", "cloud", "enterprise",
        "b2b", "b2c", "growth", "monetization",
    ]
    for trigger in industry_triggers:
        if trigger in fa_lower:
            return True

    # Candidate background mentions a specific company
    bg_lower = candidate_background.lower()
    background_signals = ["at ", "from ", "joined ", "worked at ", "formerly at ", "ex-"]
    for signal in background_signals:
        if signal in bg_lower:
            return True

    return False


def _extract_company(role: str, focus_area: str, candidate_background: str) -> Optional[str]:
    """
    Attempts to extract a company name from the interview context.
    Returns None if no specific company can be reliably identified.
    """
    combined = f"{role} {focus_area} {candidate_background}"

    # Well-known tech/product companies — check first (highest precision)
    well_known = [
        "Google", "Meta", "Amazon", "Apple", "Microsoft", "Netflix",
        "Stripe", "Airbnb", "Uber", "Lyft", "Spotify", "Shopify",
        "Salesforce", "Adobe", "Atlassian", "Figma", "Notion",
        "OpenAI", "Anthropic", "Slack", "Zoom", "Twilio", "Datadog",
        "Snowflake", "Databricks", "MongoDB", "Elastic", "HashiCorp",
        "Palantir", "Asana", "Dropbox", "Box", "HubSpot", "Zendesk",
        "Canva", "Intercom", "Segment", "Amplitude", "Mixpanel",
        "Linear", "Vercel", "Supabase", "PlanetScale", "Confluent",
    ]
    combined_lower = combined.lower()
    for name in well_known:
        if name.lower() in combined_lower:
            return name

    # Generic pattern: "at CompanyName" / "for CompanyName" (capitalised word)
    _false_positive_words = {
        "the", "a", "an", "my", "our", "your", "this", "that", "is",
        "are", "was", "were", "be", "been", "have", "has", "had",
        "will", "would", "could", "should", "may", "might",
    }
    patterns = [
        r"\bat\s+([A-Z][a-zA-Z0-9\-]{2,30})\b",
        r"\bfor\s+([A-Z][a-zA-Z0-9\-]{2,30})\b",
        r"\bwith\s+([A-Z][a-zA-Z0-9\-]{2,30})\b",
        r"\b([A-Z][a-zA-Z0-9\-]{2,30})\s+(?:interview|role|position|PM|product manager)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, combined)
        if m:
            candidate = m.group(1)
            if candidate.lower() not in _false_positive_words:
                return candidate

    return None


def _build_queries(
    company: Optional[str],
    focus_area: str,
    role: str,
) -> list[str]:
    """Builds 1-2 targeted, high-signal search queries."""
    year = datetime.now(timezone.utc).year
    queries: list[str] = []

    if company:
        queries.append(f"{company} product strategy {year}")
        if any(kw in role.lower() for kw in ("product", "pm", "manager")):
            queries.append(f"{company} product roadmap launches {year}")
    else:
        queries.append(f"{focus_area} industry trends {year}")

    return queries[:2]


# ─────────────────────────────────────────────────────────────────────────────
# Search providers
# ─────────────────────────────────────────────────────────────────────────────

def _search(query: str) -> list[dict]:
    """Dispatches to the best available provider with automatic fallback."""
    if os.environ.get("TAVILY_API_KEY"):
        try:
            results = _search_tavily(query)
            if results:
                return results
        except Exception as exc:
            logger.warning(f"[Retrieval] Tavily error: {exc}")

    if os.environ.get("SERPER_API_KEY"):
        try:
            results = _search_serper(query)
            if results:
                return results
        except Exception as exc:
            logger.warning(f"[Retrieval] Serper error: {exc}")

    try:
        return _search_duckduckgo(query)
    except Exception as exc:
        logger.warning(f"[Retrieval] DuckDuckGo error: {exc}")

    return []


def _search_tavily(query: str) -> list[dict]:
    """Tavily AI search — returns pre-cleaned snippets with URLs."""
    api_key = os.environ["TAVILY_API_KEY"]
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": _MAX_SNIPPETS,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
            "title": r.get("title", ""),
            "date": r.get("published_date", ""),
        }
        for r in data.get("results", [])
        if r.get("content")
    ]


def _search_serper(query: str) -> list[dict]:
    """Serper.dev — Google Search API."""
    api_key = os.environ["SERPER_API_KEY"]
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": _MAX_SNIPPETS},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {
            "url": r.get("link", ""),
            "snippet": r.get("snippet", ""),
            "title": r.get("title", ""),
            "date": r.get("date", ""),
        }
        for r in data.get("organic", [])
        if r.get("snippet")
    ]


def _search_duckduckgo(query: str) -> list[dict]:
    """
    DuckDuckGo Instant Answer API — free, no key required.
    Returns limited results (instant answer + related topics).
    Quality is lower than Tavily/Serper; used only as a last resort.
    """
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            headers={"User-Agent": "InterviewCoach/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()

    results: list[dict] = []

    abstract = data.get("AbstractText", "").strip()
    if abstract:
        results.append({
            "url": data.get("AbstractURL", ""),
            "snippet": abstract[:500],
            "title": data.get("Heading", ""),
            "date": "",
        })

    for topic in data.get("RelatedTopics", [])[:4]:
        if isinstance(topic, dict) and topic.get("Text"):
            results.append({
                "url": topic.get("FirstURL", ""),
                "snippet": topic["Text"][:300],
                "title": "",
                "date": "",
            })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# LLM compression
# ─────────────────────────────────────────────────────────────────────────────

_COMPRESS_SYSTEM = """\
You compress raw web-search snippets into a short, factual context block.
Output ONLY the compressed summary — no preamble, no source citations, no meta-commentary.
Target: 80-120 words. Be specific and factual. Omit speculation, PR language, and anything promotional.
Focus on: products shipped, strategy shifts, competitive positioning, key metrics, and recent launches.
"""


def _compress(
    snippets: list[dict],
    company: Optional[str],
    focus_area: str,
    role: str,
) -> str:
    """
    Compresses raw search snippets into ≤120 words using the Gemini LLM.
    Falls back to a truncated snippet if the LLM call fails.
    """
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        snippets_text = "\n\n".join(
            f"[{i + 1}] {s.get('title', '').strip()}\n{s.get('snippet', '').strip()}"
            for i, s in enumerate(snippets)
            if s.get("snippet")
        )
        subject = company if company else focus_area
        user_prompt = (
            f"Compress these search results about '{subject}' into an 80-120 word factual summary "
            f"suitable for a {role} interview context. Focus on recent products, strategy, and "
            f"competitive positioning.\n\nSEARCH RESULTS:\n{snippets_text}"
        )
        response = client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_COMPRESS_SYSTEM,
                temperature=0.1,
                max_output_tokens=_COMPRESS_MAX_TOKENS,
            ),
        )
        return (response.text or "").strip()

    except Exception as exc:
        logger.warning(f"[Retrieval] Compression LLM call failed: {exc}")
        # Graceful fallback: use the first snippet verbatim (truncated)
        for s in snippets:
            text = s.get("snippet", "").strip()
            if text:
                return text[:400]
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    """Returns the bare domain from a URL (e.g. 'quora.com')."""
    m = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1).lower() if m else ""
