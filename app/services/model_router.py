"""Model router — determines which provider/model to use per pipeline phase.

Routes between Gemini (3.5 Flash), OpenAI (gpt-5.5), and Gemini Deep Research
based on task type and API key availability.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Default Gemini models (override with env vars)
GEMINI_DEFAULT = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")       # Fast, cheap
GEMINI_PRO = os.getenv("GEMINI_PRO_MODEL", "gemini-3.1-pro-preview")  # Higher quality for synthesis

# OpenAI reasoning model for synthesis/analysis
OPENAI_REASONING = os.getenv("OPENAI_REASONING_MODEL", "gpt-5.5")

# Gemini Deep Research agent identifier
GEMINI_DEEP_RESEARCH = "deep-research-max-preview-04-2026"

# Phase routing configuration
# "gemini" = Gemini 3.5 Flash (fast, cheap, good for structured output + tools)
# "gemini_pro" = Gemini 3.1 Pro (higher quality for synthesis/analysis)
# "openai" = OpenAI gpt-5.5 (deep reasoning, synthesis, contradiction detection)
# "gemini_deep" = Gemini Deep Research (autonomous multi-step research agent)
# "auto" = use OpenAI if available, else Gemini Pro
PHASE_ROUTING = {
    "query_analysis": "gemini",         # Cheap, fast, simple task
    "study_planning": "gemini",         # Fast structuring
    "study_research": "gemini",         # Needs google_search grounding tool
    "study_research_complex": "gemini_deep",  # Full autonomous research
    "study_synthesis": "auto",          # gpt-5.5 > gemini pro > gemini flash
    "master_synthesis": "auto",         # Deep reasoning for cross-study synthesis
    "claim_validation": "auto",         # Contradiction detection
    "synthesis_evaluation": "gemini",   # Structured JSON output
    "verification": "gemini",           # Needs web_search tool (fact-checker/DA)
    "strategic_analysis": "gemini_pro", # Pro for deeper strategic insight
    "qa_anticipation": "gemini",        # Creative, cheap
}


def has_openai() -> bool:
    """Check if OpenAI API key is configured."""
    return bool(os.getenv("OPENAI_API_KEY", ""))


def has_gemini_deep_research() -> bool:
    """Check if Gemini Deep Research is available (needs GOOGLE_API_KEY)."""
    return bool(os.getenv("GOOGLE_API_KEY", ""))


def use_v2_pipeline() -> bool:
    """Return True only when LUMINARY_V2_PIPELINE=='1'.

    Strict equality check — any other value (including 'true', 'yes', '0', '') is False.
    This avoids accidental enablement from leftover env settings or typos.
    """
    return os.getenv("LUMINARY_V2_PIPELINE", "") == "1"


def get_model_for_phase(phase: str) -> tuple[str, str]:
    """Get (provider, model) for a pipeline phase.

    Returns:
        ("gemini", "gemini-3.5-flash") or
        ("openai", "gpt-5.5") or
        ("gemini_deep", "deep-research-max-preview-04-2026")
    """
    routing = PHASE_ROUTING.get(phase, "gemini")

    if routing == "auto":
        if has_openai():
            return ("openai", OPENAI_REASONING)
        return ("gemini", GEMINI_PRO)

    if routing == "gemini_pro":
        return ("gemini", GEMINI_PRO)

    if routing == "openai":
        if has_openai():
            return ("openai", OPENAI_REASONING)
        logger.warning("Phase '%s' wants OpenAI but no API key, falling back to Gemini Pro", phase)
        return ("gemini", GEMINI_PRO)

    if routing == "gemini_deep":
        if has_gemini_deep_research():
            return ("gemini_deep", GEMINI_DEEP_RESEARCH)
        logger.warning("Phase '%s' wants Gemini Deep Research but no API key, falling back to Gemini", phase)
        return ("gemini", GEMINI_DEFAULT)

    return ("gemini", GEMINI_DEFAULT)


def should_use_deep_research(study: dict, query_analysis: dict) -> bool:
    """Determine if a study should use Gemini Deep Research instead of iterative researcher.

    Uses Gemini Deep Research for complex, analytical, or multi-domain studies.
    """
    if not has_gemini_deep_research():
        return False

    complexity = query_analysis.get("complexity", "medium")
    domains = query_analysis.get("domains", [])

    # Complex studies benefit from deep research
    if complexity == "high":
        return True

    # Financial, regulatory, and multi-domain studies benefit
    high_value_domains = {"finance", "law", "regulation", "healthcare", "economics"}
    if any(d.lower() in high_value_domains for d in domains):
        return True

    # Studies with explicit "recommended_role" are specialized → deep research
    if study.get("recommended_role") and study["recommended_role"] != "general":
        return True

    return False


def get_gemini_model() -> str:
    """Get the default Gemini model name."""
    return GEMINI_DEFAULT
