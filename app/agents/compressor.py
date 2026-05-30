"""Compress a researcher's raw round output while preserving every URL and numeric token.

Used in Phase 2 of the V2 pipeline to keep synthesis-state size bounded.
Fail-open: returns the original text on any model error.
"""

import logging
import os

from app.services.research_stats import increment

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """You are a research-output compressor. Compress the following text to roughly {target_tokens} tokens.

RULES (non-negotiable):
- Every URL in the input MUST appear verbatim in the output. Copy URLs character-for-character.
- Every numeric token (percentages, dollar amounts, dates, counts, ratios) MUST appear verbatim.
- Preserve authority tags like [HIGH AUTHORITY] / [MEDIUM AUTHORITY] / [LOW AUTHORITY] next to their URLs.
- Compress narrative, examples, and restated context. Do not compress facts or sources.
- Output only the compressed text. No preamble, no explanation.

INPUT:
{raw}
"""


def _call_gemini_flash(prompt: str) -> str:
    from google import genai
    api_key = os.getenv("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
    )
    return resp.text or ""


def compress_findings(raw: str, target_tokens: int = 800, preserve_urls: bool = True) -> str:
    if not raw:
        return raw
    increment("compressor_calls")
    increment("compressor_bytes_in", len(raw))
    try:
        prompt = _PROMPT_TEMPLATE.format(target_tokens=target_tokens, raw=raw)
        if preserve_urls:
            prompt += "\n\nReminder: every URL MUST be preserved verbatim.\n"
        out = _call_gemini_flash(prompt)
        if not out:
            logger.warning("Compressor returned empty output, falling back to raw")
            return raw
        increment("compressor_bytes_out", len(out))
        return out
    except Exception:
        logger.exception("Compressor failed, returning raw input")
        return raw
