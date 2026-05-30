"""Robust JSON parsing for LLM output."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MAX_LOG_SNIPPET = 500


def _extract_balanced(text: str, open_char: str, close_char: str) -> Optional[str]:
    """Return the first balanced span in text, respecting JSON string literals."""
    start = text.find(open_char)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_json_response(text: str) -> Any:
    """Parse JSON from LLM output, stripping markdown fences and preamble."""
    if not text:
        return None

    cleaned = re.sub(r"```(?:json|JSON)?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass

    # Pick whichever opener comes first in the text.
    obj_idx = cleaned.find("{")
    arr_idx = cleaned.find("[")
    order: List[Tuple[str, str]] = []
    if arr_idx != -1 and (obj_idx == -1 or arr_idx < obj_idx):
        order = [("[", "]"), ("{", "}")]
    elif obj_idx != -1:
        order = [("{", "}"), ("[", "]")]
    for opener, closer in order:
        span = _extract_balanced(cleaned, opener, closer)
        if span is not None:
            try:
                return json.loads(span)
            except (json.JSONDecodeError, TypeError):
                continue

    snippet = text.strip().replace("\n", " ")
    if len(snippet) > _MAX_LOG_SNIPPET:
        snippet = snippet[:_MAX_LOG_SNIPPET] + "...<truncated>"
    logger.warning("parse_json_response: could not parse LLM output; snippet=%r", snippet)
    return None
